import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Quiz, QuizResponse, Room, User, Summary, ChatMessage
from transformers import pipeline
import logging
import re
import torch

logger = logging.getLogger(__name__)

class RoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'room_{self.room_id}'
        self.user = self.scope['user']

        # Log the user to debug authentication issues
        logger.info(f"User in scope: {self.user}, is_authenticated: {self.user.is_authenticated if self.user else False}")

        # If the user is not authenticated, try to get the user from the session
        if not self.user or not self.user.is_authenticated:
            session_user_email = self.scope['session'].get('user_email')
            if session_user_email:
                self.user = await self.get_user_by_email(session_user_email)
                logger.info(f"User retrieved from session: {self.user}")
            else:
                logger.warning("No user found in session. Closing WebSocket connection.")
                await self.close()
                return

        # If we still don't have a valid user, close the connection
        if not self.user:
            logger.error("No valid user found. Closing WebSocket connection.")
            await self.close()
            return

        # Fetch the room object for use in the consumer
        self.room = await self.get_room(self.room_id)
        if not self.room:
            logger.error(f"Room {self.room_id} does not exist.")
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
        logger.info(f"WebSocket connected for user {self.user} in room {self.room_id}. Group: {self.room_group_name}, Channel: {self.channel_name}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        logger.info(f"WebSocket disconnected for user {self.user} in room {self.room_id}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            message = data.get('message')

            logger.info(f"Received message from {self.user}: {message}")

            if message_type == 'chat_message':
                is_ai_message = message.strip().startswith('@ai')
                mentioned_users = []

                if not is_ai_message:
                    mentions = re.findall(r'@([\w\s]+)\b', message)
                    logger.info(f"Extracted mentions: {mentions}")
                    mentioned_users = await self.get_mentioned_users(mentions)

                chat_message = await self.save_chat_message(
                    room_id=self.room_id,
                    sender=self.user,  # Use self.user directly
                    message=message,
                    is_ai_response=False
                )

                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': message,
                        'user_id': self.user.id,  # Send user_id for alignment
                        'username': self.user.name if self.user.name else self.user.email.split('@')[0],  # Fallback to email prefix if name is None
                        'timestamp': chat_message.timestamp.isoformat(),
                        'mentions': mentioned_users,
                        'is_ai_response': False
                    }
                )

                if is_ai_message:
                    ai_response = await self.handle_ai_message(message, self.room_id)
                    ai_chat_message = await self.save_chat_message(
                        room_id=self.room_id,
                        sender=None,  # AI has no sender
                        message=ai_response,
                        is_ai_response=True
                    )
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'chat_message',
                            'message': ai_response,
                            'user_id': None,  # No user_id for AI
                            'username': 'AI',
                            'timestamp': ai_chat_message.timestamp.isoformat(),
                            'mentions': [],
                            'is_ai_response': True
                        }
                    )
            elif message_type == 'quiz_response':
                quiz_id = data.get('quiz_id')
                selected_answer = data.get('selected_answer')
                await self.save_quiz_response(quiz_id, self.user, selected_answer)
                logger.info(f"Quiz response saved: {self.user} answered {selected_answer} for quiz {quiz_id}")
        except Exception as e:
            logger.error(f"Error in WebSocket receive: {str(e)}", exc_info=True)
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error processing message: {str(e)}'
            }))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'user_id': event['user_id'],
            'username': event['username'],
            'timestamp': event['timestamp'],
            'mentions': event['mentions'],
            'is_ai_response': event['is_ai_response']
        }))

    async def summarizing_start(self, event):
        await self.send(text_data=json.dumps({
            'type': 'summarizing_start',
            'message': event['message']
        }))

    async def broadcast_chunk_summary(self, event):
        summary = event['summary']
        chunk_number = event['chunk_number']
        await self.send(text_data=json.dumps({
            'type': 'chunk_summary',
            'summary': summary,
            'chunk_number': chunk_number
        }))

    async def broadcast_summary(self, event):
        summary = event['summary']
        username = event['username']
        pdf_name = event['pdf_name']
        logger.info(f"Sending broadcast_summary to user {self.user} in room {self.room_id}: {summary[:50]}...")
        await self.send(text_data=json.dumps({
            'type': 'final_summary',
            'summary': summary,
            'username': username,
            'pdf_name': pdf_name
        }))

    async def room_notification(self, event):
        message = event['message']
        username = event['username']
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'message': message,
            'username': username
        }))

    async def quiz_start_notification(self, event):
        print(f"Sending quiz start notification to room {self.room_id}: {event['message']}")
        await self.send(text_data=json.dumps({
            'type': 'quiz_start_notification',
            'message': event['message']
        }))

    @database_sync_to_async
    def save_chat_message(self, room_id, sender, message, is_ai_response):
        room = Room.objects.get(id=room_id)
        chat_message = ChatMessage.objects.create(
            room=room,
            sender=sender if not is_ai_response else None,
            message=message,
            is_ai_response=is_ai_response
        )
        logger.info(f"Saved chat message: {chat_message}")
        return chat_message

    @database_sync_to_async
    def get_mentioned_users(self, mentions):
        mentioned_users = []
        for mention in mentions:
            try:
                user = User.objects.get(name__iexact=mention.strip())
                mentioned_users.append(user.name)
            except User.DoesNotExist:
                logger.warning(f"Mentioned user not found: {mention}")
                continue
        return mentioned_users

    @database_sync_to_async
    def get_user_by_email(self, email):
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            logger.warning(f"User with email {email} not found.")
            return None

    @database_sync_to_async
    def get_room(self, room_id):
        try:
            return Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return None

    @database_sync_to_async
    def get_room_summaries(self, room_id):
        room = Room.objects.get(id=room_id)
        summaries = room.summaries.all()
        return [summary.summary_text for summary in summaries]

    async def handle_ai_message(self, message, room_id):
        try:
            question = message.replace('@ai', '').strip()
            if not question:
                return "Please ask a valid question after @ai."

            summaries = await self.get_room_summaries(room_id)
            if not summaries:
                return "No summaries available to answer questions. Please upload a PDF first."

            context = " ".join(summaries)

            device = 0 if torch.cuda.is_available() else -1
            qa_pipeline = pipeline(
                "question-answering",
                model="distilbert-base-uncased-distilled-squad",
                device=device
            )
            logger.info(f"QA pipeline initialized on {'GPU' if device == 0 else 'CPU'}")

            result = qa_pipeline({
                'question': question,
                'context': context
            })
            answer = result['answer']
            logger.info(f"AI answered: {answer} for question: {question}")
            return answer

        except Exception as e:
            logger.error(f"Error in AI question answering: {str(e)}")
            return f"Sorry, I couldn't process your question: {str(e)}"

    async def broadcast_quiz(self, event):
        await self.send(text_data=json.dumps({
            'type': 'quiz',
            'quizzes': event['quizzes']
        }))

    async def broadcast_ranking(self, event):
        await self.send(text_data=json.dumps({
            'type': 'ranking',
            'rankings': event['rankings']
        }))

    @database_sync_to_async
    def save_quiz_response(self, quiz_id, user, selected_answer):
        try:
            quiz = Quiz.objects.get(id=quiz_id)
            QuizResponse.objects.update_or_create(
                quiz=quiz,
                user=user,
                room=self.room,
                defaults={'selected_answer': selected_answer}
            )
            logger.info(f"Saved quiz response for quiz_id {quiz_id}, user {user}, answer {selected_answer}")
        except Exception as e:
            logger.error(f"Error saving quiz response: {str(e)}")
            raise