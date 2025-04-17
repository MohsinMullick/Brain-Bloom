import uuid
from django.shortcuts import render, redirect
from django.core.mail import send_mail
from django.core.files.storage import FileSystemStorage
from django.conf import settings
import random
from django.db.models import Q
from django.db import transaction
from .tasks import generate_quiz_questions
from .models import ChatMessage, Note, NoteReview, QuizResponse, Review, StudyPartnerRequest, User, OTP, Room, Summary, Quiz
from .forms import ReviewForm, SignUpForm, OTPVerificationForm, PasswordRecoveryForm, PasswordRecoveryOTPForm, NewPasswordForm, ProfileUpdateForm
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import date, time, datetime, timedelta
from django.views.decorators.cache import never_cache
import pytz
import PyPDF2
import logging
import re
import torch
from django.http import JsonResponse
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from PIL import Image
import io
import fitz
import pytesseract
import json
from transformers import pipeline
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.http import FileResponse
from accounts import models

logger = logging.getLogger(__name__)

# Ensure logger uses UTF-8 encoding
for handler in logger.handlers:
    if isinstance(handler, logging.FileHandler):
        handler.setStream(open(handler.baseFilename, 'a', encoding='utf-8'))

def broadcast_summary(room_id, summary, uploader_name, pdf_name):
    channel_layer = get_channel_layer()
    logger.info(f"Broadcasting summary to group room_{room_id}: {summary[:50]}... by {uploader_name}")
    async_to_sync(channel_layer.group_send)(
        f'room_{room_id}',
        {
            'type': 'broadcast_summary',
            'summary': summary,
            'username': uploader_name,
            'pdf_name': pdf_name,
        }
    )

def broadcast_summarizing_start(room_id):
    channel_layer = get_channel_layer()
    logger.info(f"Broadcasting summarizing_start to group room_{room_id}")
    async_to_sync(channel_layer.group_send)(
        f'room_{room_id}',
        {
            'type': 'summarizing_start',
            'message': 'PDF summarization started.'
        }
    )

def broadcast_chunk_summary(room_id, summary, chunk_number):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'room_{room_id}',
        {
            'type': 'broadcast_chunk_summary',
            'summary': summary,
            'chunk_number': chunk_number,
        }
    )

def extract_text_from_pdf(file_path):
    text = ''
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    
    with open(file_path, 'rb') as f:
        pdf = PyPDF2.PdfReader(f)
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ''
            if page_text.strip():
                cleaned_text = re.sub(r'[^\w\s.,!?()\-]', ' ', page_text)
                text += cleaned_text + ' '
            else:
                try:
                    doc = fitz.open(file_path)
                    pdf_page = doc.load_page(i)
                    pix = pdf_page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
                    img = pix.tobytes("png")
                    doc.close()

                    image = Image.open(io.BytesIO(img))
                    ocr_text = pytesseract.image_to_string(image)
                    if ocr_text.strip():
                        cleaned_ocr_text = re.sub(r'[^\w\s.,!?()\-]', ' ', ocr_text)
                        text += cleaned_ocr_text + ' '

                    from transformers import pipeline
                    image_captioner = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base", device=-1)
                    caption = image_captioner(image)[0]['generated_text']
                    logger.info(f"Image caption on page {i+1}: {caption}")
                    text += caption + ' '
                except Exception as e:
                    logger.error(f"OCR or captioning failed for page {i+1}: {str(e)}")
    return text.strip()

def get_resources(key_points, summary_text):
    resources = []
    query = f"{key_points[0]} tutorial" if key_points else summary_text[:50].replace(' ', '+')
    resources.append({
        'type': 'Google',
        'link': f"https://www.google.com/search?q={query}"
    })
    resources.append({
        'type': 'YouTube',
        'link': f"https://www.youtube.com/results?search_query={query}"
    })
    return resources

def home(request):
    return render(request, 'home.html')

def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            if not email.endswith('@northsouth.edu'):
                form.add_error('email', 'Email must be from @northsouth.edu domain.')
                return render(request, 'signup.html', {'form': form})
            
            user = form.save(commit=False)
            user.password = form.cleaned_data['password']
            user.name = form.cleaned_data['name'].strip()  # Ensure name is stripped
            user.save()

            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            OTP.objects.create(email=email, otp=otp)

            send_mail(
                'OTP for Verification',
                f'Your OTP is {otp}',
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )

            return redirect('otp_verification')
    else:
        form = SignUpForm()
    return render(request, 'signup.html', {'form': form})

def otp_verification(request):
    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            try:
                otp_record = OTP.objects.get(otp=otp)
                user = User.objects.get(email=otp_record.email)
                user.is_verified = True
                user.save()
                otp_record.delete()
                return redirect('login')
            except OTP.DoesNotExist:
                form.add_error('otp', 'Invalid OTP')
    else:
        form = OTPVerificationForm()
    return render(request, 'otp_verification.html', {'form': form})

def login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        try:
            user = User.objects.get(email=email, password=password, is_verified=True)
            request.session['user_email'] = user.email
            return redirect('dashboard')
        except User.DoesNotExist:
            return render(request, 'login.html', {'error': 'Invalid credentials or user not verified.'})
    return render(request, 'login.html')

def logout(request):
    # Clear the session
    request.session.flush()
    logger.info("User logged out, session cleared")
    return redirect('login')
@never_cache
def profile_settings(request):
    if 'user_email' not in request.session:
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    context = {
        'user': user,
    }
    return render(request, 'profile_settings.html', context)

@never_cache
def update_profile(request):
    if 'user_email' not in request.session:
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    
    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            user = form.save(commit=False)
            user.name = user.name.strip()  # Ensure name is stripped
            user.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile_settings')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ProfileUpdateForm(instance=user)
    
    context = {
        'form': form,
        'user': user,
    }
    return render(request, 'update_profile.html', context)
@never_cache
def dashboard(request):
    logger.info(f"Session data: {request.session.items()}")
    if 'user_email' not in request.session:
        logger.warning("No user_email in session, redirecting to login")
        return redirect('login')
    
    try:
        user = User.objects.get(email=request.session['user_email'])
        logger.info(f"User loaded in dashboard: email={user.email}, id={user.id}, name={user.name}")
    except User.DoesNotExist:
        logger.error(f"User with email {request.session['user_email']} not found")
        return redirect('login')
    review_form = ReviewForm()  # Default empty form
    
    if request.method == 'POST':
        # Handle review submission
        if 'submit_review' in request.POST:
            review_form = ReviewForm(request.POST)
            if review_form.is_valid():
                review = review_form.save(commit=False)
                review.user = user
                review.save()
                messages.success(request, 'Review submitted successfully!')
                return redirect('dashboard')
    rooms = Room.objects.filter(Q(creator=user) | Q(participants=user))
    for room in rooms:
        if room.is_expired():
            room.delete()
            messages.success(request, f'Expired room "{room.title}" has been automatically deleted.')

    today = date.today()
    created_rooms = Room.objects.filter(creator=user)
    created_todays_rooms = created_rooms.filter(date=today)
    created_upcoming_rooms = created_rooms.filter(date__gt=today)
    
    joined_rooms = Room.objects.filter(participants=user).exclude(creator=user)
    joined_todays_rooms = joined_rooms.filter(date=today)
    joined_upcoming_rooms = joined_rooms.filter(date__gt=today)
    
    todays_rooms = (created_todays_rooms | joined_todays_rooms).distinct()
    upcoming_rooms = (created_upcoming_rooms | joined_upcoming_rooms).distinct()
    
    todays_rooms_dict = {}
    for room in todays_rooms:
        key = (room.title, room.date, room.time)
        if key not in todays_rooms_dict:
            todays_rooms_dict[key] = room
            tz = pytz.timezone('Asia/Dhaka')
            start_datetime = tz.localize(datetime.combine(room.date, room.time))
            current_time = timezone.now().astimezone(tz)
            end_time = room.get_end_time()
            room.is_accessible = current_time >= start_datetime and current_time <= end_time
    todays_rooms = list(todays_rooms_dict.values())
    
    upcoming_rooms_dict = {}
    for room in upcoming_rooms:
        key = (room.title, room.date, room.time)
        if key not in upcoming_rooms_dict:
            upcoming_rooms_dict[key] = room
            tz = pytz.timezone('Asia/Dhaka')
            start_datetime = tz.localize(datetime.combine(room.date, room.time))
            current_time = timezone.now().astimezone(tz)
            end_time = room.get_end_time()
            room.is_accessible = current_time >= start_datetime and current_time <= end_time
    upcoming_rooms = list(upcoming_rooms_dict.values())
    notes = Note.objects.all().order_by('-uploaded_at')
    study_partner_recommendations = get_study_partner_recommendations(user)

    # Define pending_requests
    pending_requests = StudyPartnerRequest.objects.filter(
        receiver=user,
        status='pending'
    ).select_related('sender')
    logger.info(f"Pending requests for user {user.email} (ID: {user.id}): {list(pending_requests.values('id', 'sender__email', 'receiver__email', 'status'))}")
    accepted_requests = StudyPartnerRequest.objects.filter(
        Q(sender=user, status='accepted') | Q(receiver=user, status='accepted')
    ).select_related('sender', 'receiver')
    logger.debug(f"Accepted study partners for user {user.name}: {accepted_requests.count()}")
    for req in accepted_requests:
        logger.debug(f"Accepted request ID {req.id}: Sender={req.sender.name if req.sender else 'None'}, Receiver={req.receiver.name if req.receiver else 'None'}, Status={req.status}")

    # Fetch accepted study partners
    accepted_partners = StudyPartnerRequest.objects.filter(
        Q(sender=user, status='accepted') | Q(receiver=user, status='accepted')
    ).select_related('sender', 'receiver')


   
    context = {
        'user': user,
        'todays_rooms': todays_rooms,
        'upcoming_rooms': upcoming_rooms,
        'notes': notes,
        'study_partner_recommendations': study_partner_recommendations,
        'pending_requests': pending_requests,
        'accepted_partners': accepted_partners,
        'review_form': review_form,
    }
    logger.info(f"Context passed to template: {context}")

    # Add final check before rendering
    logger.info(f"Final pending_requests before rendering: {list(context['pending_requests'].values('id', 'sender__email', 'receiver__email', 'status'))}")
    return render(request, 'dashboard.html', context)
def home(request):
    reviews = Review.objects.filter(approved=True).order_by('-created_at')[:10]
    return render(request, 'home.html', {'reviews': reviews})

def public_rooms(request):
    if 'user_email' not in request.session:
        return redirect('login')
    
    query = request.GET.get('q', '')
    public_rooms = Room.objects.filter(visibility='public')
    if query:
        public_rooms = public_rooms.filter(Q(title__icontains=query) | Q(department__icontains=query) | Q(course__icontains=query))
    
    context = {
        'public_rooms': public_rooms,
        'query': query,
    }
    return render(request, 'public_rooms.html', context)

def private_room(request, room_id):
    if 'user_email' not in request.session:
        return redirect('login')
    
    try:
        room = Room.objects.get(id=room_id, visibility='private')
        user = User.objects.get(email=request.session['user_email'])

        if request.method == 'POST':
            code = request.POST.get('code', '')
            if code == room.code:
                if user in room.participants.all():
                    messages.info(request, 'You are already a member of this room.')
                else:
                    room.participants.add(user)
                    messages.success(request, f'Joined {room.title} successfully!')
                return redirect('private_room', room_id=room.id)
            else:
                messages.error(request, 'Invalid room code.')

        if user in room.participants.all() or room.creator == user:
            context = {'room': room}
            return render(request, 'private_room.html', context)
        else:
            context = {'room': room, 'show_code_form': True}
            return render(request, 'private_room.html', context)
    except Room.DoesNotExist:
        messages.error(request, 'Private room not found.')
        return redirect('dashboard')

def room_dashboard(request):
    if 'user_email' not in request.session:
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    joined_rooms = Room.objects.filter(
        Q(participants=user) | Q(creator=user)
    ).distinct()
    
    rooms_data = []
    tz = pytz.timezone('Asia/Dhaka')
    current_time = timezone.now().astimezone(tz)
    
    for room in joined_rooms:
        start_datetime = room.get_start_datetime()
        study_end = start_datetime + timedelta(minutes=20)
        quiz_start = study_end
        quiz_end = quiz_start + timedelta(minutes=7)
        is_expired = current_time > quiz_end

        room.is_accessible = current_time >= start_datetime and current_time <= quiz_end

        quizzes = Quiz.objects.filter(room=room)
        for quiz in quizzes:
            if isinstance(quiz.options, str):
               quiz.options = json.loads(quiz.options)
        
        quiz_responses = QuizResponse.objects.filter(room=room, user=user)
        has_submitted_quiz = False
        score = 0
        if quizzes.exists():
            submitted_quiz_ids = set(quiz_responses.values_list('quiz_id', flat=True))
            all_quiz_ids = set(quizzes.values_list('id', flat=True))
            has_submitted_quiz = submitted_quiz_ids == all_quiz_ids
            if has_submitted_quiz:
                score = sum(1 for response in quiz_responses if response.selected_answer == response.quiz.correct_answer)

        rooms_data.append({
            'room': room,
            'is_expired': is_expired,
            'has_quiz': quizzes.exists(),
            'has_submitted_quiz': has_submitted_quiz,
            'score': score,
        })
    
    context = {
        'joined_rooms': rooms_data,
    }
    return render(request, 'room_dashboard.html', context)

@require_POST
def join_room_base(request):
    if 'user_email' not in request.session:
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    code = request.POST.get('code')
    
    if code:
        try:
            room = Room.objects.get(code=code)
            if room.visibility == 'public':
                if user in room.participants.all():
                    messages.info(request, 'You are already a member of this room.')
                else:
                    room.participants.add(user)
                    messages.success(request, f'Joined {room.title} successfully!')
                return redirect('public_room_details', room_id=room.id)
            elif room.visibility == 'private':
                if code == room.code:
                    if user in room.participants.all():
                        messages.info(request, 'You are already a member of this room.')
                    else:
                        room.participants.add(user)
                        messages.success(request, f'Joined {room.title} successfully!')
                    return redirect('private_room', room_id=room.id)
                else:
                    messages.error(request, 'Invalid room code.')
                    return render(request, 'join_room.html')
        except Room.DoesNotExist:
            messages.error(request, 'Room not found with this code.')
            return render(request, 'join_room.html')
    else:
        messages.error(request, 'Please enter a room code.')
        return render(request, 'join_room.html')

@require_POST
def create_room(request):
    if 'user_email' not in request.session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'User not logged in.'}, status=401)
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    
    department = request.POST.get('department')
    course = request.POST.get('course')
    topic = request.POST.get('topic')
    date_str = request.POST.get('date')
    time_str = request.POST.get('time')
    visibility = request.POST.get('visibility')
    
    logger.debug(f"Received data: department={department}, course={course}, topic={topic}, date={date_str}, time={time_str}, visibility={visibility}")
    
    if all([department, course, topic, date_str, time_str, visibility]):
        try:
            room_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            logger.debug(f"Parsed date: {room_date}")
            current_date = date.today()
            if room_date < current_date:
                logger.error(f"Cannot create room in the past. Room date: {room_date}, Current date: {current_date}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Cannot create a room in the past.'})
                messages.error(request, 'Cannot create a room in the past.')
                return redirect('dashboard')
        except ValueError as e:
            logger.error(f"Date parsing error: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'Invalid date format. Use YYYY-MM-DD.'})
            messages.error(request, 'Invalid date format. Use YYYY-MM-DD.')
            return redirect('dashboard')
        
        try:
            room_time = datetime.strptime(time_str, '%H:%M').time()
            logger.debug(f"Parsed time: {room_time}")
        except ValueError as e:
            logger.error(f"Time parsing error: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'Invalid time format. Use HH:MM.'})
            messages.error(request, 'Invalid time format. Use HH:MM.')
            return redirect('dashboard')
        
        try:
            title = f"{topic} ({course})"
            room = Room.objects.create(
                creator=user,
                title=title,
                topic=topic,
                department=department,
                course=course,
                date=room_date,
                time=room_time,
                visibility=visibility
            )
            logger.debug(f"Room created: {room.id}")
            
            if visibility == 'private':
                room.code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
                room.save()
                logger.debug(f"Private room code set: {room.code}")
            
            room.participants.add(user)
            
            participants = room.participants.all()
            email_list = [user.email]
            for participant in participants:
                if participant.email not in email_list:
                    email_list.append(participant.email)
            
            start_datetime = timezone.make_aware(datetime.combine(room.date, room.time))
            notification_message = (
                f"Reminder: The room '{room.title}' is starting at {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                f"Department: {room.department}, Course: {room.course}, Visibility: {room.visibility}"
            )
            try:
                send_mail(
                    subject=f"Room Notification: {room.title}",
                    message=notification_message,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=email_list,
                    fail_silently=True,
                )
                logger.debug("Email sent successfully")
            except Exception as e:
                logger.error(f"Email sending error: {str(e)}")
                messages.error(request, f"Failed to send notification email: {str(e)}")

            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'room_{room.id}',
                    {
                        'type': 'room_notification',
                        'message': notification_message,
                        'username': user.name,
                    }
                )
                logger.debug("Channels broadcast sent successfully")
            except Exception as e:
                logger.error(f"Channels error: {str(e)}")
                messages.error(request, f"Failed to broadcast notification: {str(e)}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Room created successfully!'})
            messages.success(request, 'Room created successfully!')
        except Exception as e:
            logger.error(f"Error creating room: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': f"Error creating room: {str(e)}"})
            messages.error(request, f"Error creating room: {str(e)}")
    else:
        logger.warning("Missing required fields")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'All fields are required.'})
        messages.error(request, 'All fields are required.')
    
    return redirect('dashboard')

@require_POST
def delete_room(request, room_id):
    if 'user_email' not in request.session:
        return redirect('login')
    
    try:
        room = Room.objects.get(id=room_id, creator__email=request.session['user_email'])
        room.delete()
        messages.success(request, 'Room deleted successfully!')
    except Room.DoesNotExist:
        messages.error(request, 'Room not found or you don\'t have permission.')
    
    return redirect('dashboard')

@require_POST
def leave_room(request, room_id):
    if 'user_email' not in request.session:
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    try:
        room = Room.objects.get(id=room_id)
        if user in room.participants.all() and room.creator != user:
            room.participants.remove(user)
            messages.success(request, f'Left {room.title} successfully!')
        else:
            messages.error(request, 'You cannot leave a room you created or are not a participant of.')
        return redirect('room_dashboard')
    except Room.DoesNotExist:
        messages.error(request, 'Room not found.')
        return redirect('room_dashboard')

from django.middleware.csrf import get_token

def group_chat(request, room_id):
    if 'user_email' not in request.session:
        return redirect('login')

    try:
        room = Room.objects.get(id=room_id)
        user = User.objects.get(email=request.session['user_email'])
        user.name = user.name.strip() if user.name else user.email.split('@')[0]
        user.save()  # Ensure the name is saved
        print(f"Logged-in user.name: {user.name}, user.id: {user.id}")

        if user not in room.participants.all() and room.creator != user:
            messages.error(request, 'You must join this room first.')
            if room.visibility == 'public':
                return redirect('public_rooms')
            else:
                return redirect('private_room', room_id=room_id)

        tz = pytz.timezone('Asia/Dhaka')
        naive_start_datetime = datetime.combine(room.date, room.time)
        start_datetime = tz.localize(naive_start_datetime)
        current_time = timezone.now().astimezone(tz)

        logger.info(f"Room ID: {room.id}, Title: {room.title}")
        logger.info(f"Room date: {room.date}, Room time: {room.time}")
        logger.info(f"Naive start datetime: {naive_start_datetime}")
        logger.info(f"Localized start datetime: {start_datetime}")
        logger.info(f"Current time: {current_time}")

        study_end = start_datetime + timedelta(minutes=20)
        quiz_start = study_end
        quiz_end = quiz_start + timedelta(minutes=7)
        ranking_start = quiz_end
        room_expiry = ranking_start + timedelta(minutes=5)  # Room expires 5 minutes after ranking starts

        is_study_session = current_time < study_end
        is_quiz_session = quiz_start <= current_time < quiz_end
        is_ranking_session = ranking_start <= current_time < room_expiry
        is_expired = current_time >= room_expiry

        quiz_end_timestamp = int(quiz_end.timestamp() * 1000) if is_quiz_session else 0

        logger.info(f"Room {room.title} - Start: {start_datetime}, End: {study_end}")
        logger.info(f"Room {room.title} - Current time: {current_time}, End time: {study_end}, Expired: {current_time > study_end}")
        logger.info(f"Session states - Study: {is_study_session}, Quiz: {is_quiz_session}, Ranking: {is_ranking_session}, Expired: {is_expired}")

        can_access_chat = (start_datetime - timedelta(minutes=1)) <= current_time < room_expiry
        logger.info(f"Can access chat: {can_access_chat}")

        if not can_access_chat:
            if is_expired:
                messages.error(request, "This room has expired. You can no longer access it.")
                return redirect('room_dashboard')
            logger.info("Access denied: Current time is before the room's start time.")
            context = {
                'room': room,
                'can_access_chat': False,
            }
            return render(request, 'group_chat.html', context)

        chat_messages = ChatMessage.objects.filter(room=room).order_by('timestamp')
        for message in chat_messages:
            if message.sender:
                message.sender.name = message.sender.name.strip() if message.sender.name else message.sender.email.split('@')[0]
                message.sender.save()

        summaries = Summary.objects.filter(room=room).order_by('-uploaded_at')
        quizzes = Quiz.objects.filter(room=room)
        # Convert options to dictionary for all quizzes
        for quiz in quizzes:
            if isinstance(quiz.options, str):
                quiz.options = json.loads(quiz.options)
        quiz_responses = QuizResponse.objects.filter(room=room, user=user)

        logger.info(f"Found {summaries.count()} summaries for room {room.id}")
        for summary in summaries:
            logger.info(f"Summary {summary.id}: {summary.pdf_name}, Uploaded at: {summary.uploaded_at}")

        logger.info(f"Found {quizzes.count()} quizzes for room {room.id}")
        for quiz in quizzes:
            logger.info(f"Quiz {quiz.id}: {quiz.question}")

        has_submitted_quiz = False
        if quizzes.exists():
            submitted_quiz_ids = set(quiz_responses.values_list('quiz_id', flat=True))
            all_quiz_ids = set(quizzes.values_list('id', flat=True))
            has_submitted_quiz = submitted_quiz_ids == all_quiz_ids
            logger.info(f"Has submitted quiz: {has_submitted_quiz}")

        if current_time >= start_datetime + timedelta(minutes=18) and not room.quizzes.exists():
            pdf_texts = []
            for summary in room.summaries.all():
                fs = FileSystemStorage()
                if summary.actual_file_name:
                    try:
                        file_path = fs.path(summary.actual_file_name)
                        text = extract_text_from_pdf(file_path)
                        pdf_texts.append(text.lower())
                    except Exception as e:
                        logger.error(f"Failed to extract text from PDF {summary.actual_file_name}: {str(e)}")
                        continue

            combined_text = " ".join(pdf_texts)
            room_topic_keywords = room.title.lower().split()
            topic_match = any(keyword in combined_text for keyword in room_topic_keywords if len(keyword) > 3)
            if not topic_match:
                messages.warning(request, "The uploaded PDF content does not seem to match the room's topic. Quiz questions may be unrelated to the intended subject.")

            generate_quiz_questions(room)
            quizzes = Quiz.objects.filter(room=room)  # Refresh the queryset
            logger.info(f"Quiz questions generated for room {room_id}")

        if is_quiz_session and room.quizzes.exists():
            channel_layer = get_channel_layer()
            quiz_data = [
                {
                    'id': quiz.id,
                    'question': quiz.question,
                    'options': quiz.options,
                } for quiz in room.quizzes.all()
            ]
            async_to_sync(channel_layer.group_send)(
                f'room_{room.id}',
                {
                    'type': 'broadcast_quiz',
                    'quizzes': quiz_data,
                }
            )

        if not is_study_session and current_time < quiz_start:
            messages.info(request, 'Study session has ended. Quiz session will begin soon.')

        summary = None
        key_points = []
        resources = []
        if request.method == 'POST' and is_study_session:
            pdf_file = request.FILES.get('study_material')
            if pdf_file and pdf_file.name.endswith('.pdf'):
                existing_summary = room.summaries.filter(pdf_name=pdf_file.name).first()
                if existing_summary:
                    logger.warning(f"Summary for {pdf_file.name} already exists in room {room_id}. Skipping duplicate.")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': f"A summary for {pdf_file.name} already exists in this room."})
                    messages.warning(request, f"A summary for {pdf_file.name} already exists in this room.")
                    return redirect('group_chat', room_id=room_id)

                broadcast_summarizing_start(room_id)

                original_filename = pdf_file.name
                unique_suffix = f"{uuid.uuid4()}_{original_filename}"
                fs = FileSystemStorage()
                filename = fs.save(unique_suffix, pdf_file)
                file_path = fs.path(filename)

                text = extract_text_from_pdf(file_path)
                logger.info(f"Extracted text length: {len(text)} characters")

                if not text or len(text) < 10:
                    logger.error("Extracted text is empty or too short after cleaning.")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': "No valid text extracted from the PDF. Please upload a text-based or scannable PDF."})
                    messages.error(request, "No valid text extracted from the PDF. Please upload a text-based or scannable PDF.")
                    return redirect('group_chat', room_id=room_id)

                device = 0 if torch.cuda.is_available() else -1
                try:
                    from transformers import AutoTokenizer, pipeline
                    tokenizer = AutoTokenizer.from_pretrained("sshleifer/distilbart-cnn-12-6")
                    summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6", tokenizer=tokenizer, device=device)
                    logger.info(f"Summarizer (sshleifer/distilbart-cnn-12-6) initialized on {'GPU' if device == 0 else 'CPU'}")
                except Exception as e:
                    logger.error(f"Failed to initialize sshleifer/distilbart-cnn-12-6 summarizer: {str(e)}")
                    try:
                        tokenizer = AutoTokenizer.from_pretrained("t5-small")
                        summarizer = pipeline("summarization", model="t5-small", tokenizer=tokenizer, device=device)
                        logger.info(f"Fallback summarizer (t5-small) initialized on {'GPU' if device == 0 else 'CPU'}")
                    except Exception as e2:
                        logger.error(f"Failed to initialize fallback t5-small summarizer: {str(e2)}")
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'message': f"Failed to initialize summarizer: {str(e2)}."})
                        messages.error(request, f"Failed to initialize summarizer: {str(e2)}. Please try again.")
                        return redirect('group_chat', room_id=room_id)

                max_input_length = 1024 if "distilbart" in str(summarizer.model) else 512
                chunks = []
                encoded = tokenizer(text, truncation=False, return_tensors="pt")
                input_ids = encoded['input_ids'][0]
                token_count = len(input_ids)
                logger.info(f"Total token count: {token_count}")

                if token_count > max_input_length:
                    for i in range(0, len(input_ids), max_input_length):
                        chunk_ids = input_ids[i:i + max_input_length]
                        chunk_text = tokenizer.decode(chunk_ids, skip_special_tokens=True)
                        if chunk_text.strip():
                            chunk_text = re.sub(r'\s+', ' ', chunk_text).strip()
                            if not chunk_text.endswith(('.', '!', '?')) and len(chunks) < len(input_ids) // max_input_length - 1:
                                last_period = chunk_text.rfind('.')
                                if last_period != -1:
                                    chunk_text = chunk_text[:last_period + 1]
                            chunks.append(chunk_text)
                else:
                    chunks.append(text)

                logger.info(f"Number of chunks to summarize: {len(chunks)}")

                chunk_summaries = []
                for idx, chunk in enumerate(chunks):
                    tokens = tokenizer(chunk, truncation=True, max_length=max_input_length, return_tensors="pt", return_length=True)
                    chunk_token_count = tokens['length'].item()
                    logger.info(f"Chunk {idx + 1} token count: {chunk_token_count}")

                    if chunk_token_count > max_input_length:
                        logger.warning(f"Chunk {idx + 1} token count exceeds max_input_length after truncation. Forcing reprocessing.")
                        encoded = tokenizer(chunk, truncation=True, max_length=max_input_length, return_tensors="pt")
                        chunk = tokenizer.decode(encoded['input_ids'][0], skip_special_tokens=True)
                        tokens = tokenizer(chunk, truncation=True, max_length=max_input_length, return_tensors="pt", return_length=True)
                        chunk_token_count = tokens['length'].item()
                        logger.info(f"Chunk {idx + 1} token count after forced truncation: {chunk_token_count}")

                    max_length = min(150, max(50, chunk_token_count // 3))
                    if chunk_token_count < max_length:
                        max_length = max(10, chunk_token_count // 2)
                    min_length = min(30, max_length - 10)

                    try:
                        chunk_summary = summarizer(
                            chunk,
                            max_length=max_length,
                            min_length=min_length,
                            do_sample=False,
                            num_beams=4,
                            early_stopping=True,
                        )[0]['summary_text']
                        chunk_summaries.append(chunk_summary)
                        broadcast_chunk_summary(room_id, chunk_summary, idx + 1)
                        logger.info(f"Chunk {idx + 1} summary: {chunk_summary[:100]}...")
                    except Exception as e:
                        logger.error(f"Error summarizing chunk {idx + 1}: {str(e)} with text sample: {chunk[:100]}...")
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'message': f"Failed to summarize chunk {idx + 1}: {str(e)}."})
                        messages.error(request, f"Failed to summarize chunk {idx + 1}: {str(e)}. Falling back to t5-small.")
                        try:
                            fallback_tokenizer = AutoTokenizer.from_pretrained("t5-small")
                            fallback_summarizer = pipeline("summarization", model="t5-small", tokenizer=fallback_tokenizer, device=device)
                            chunk_summary = fallback_summarizer(
                                chunk,
                                max_length=max_length,
                                min_length=min_length,
                                do_sample=False,
                                num_beams=4,
                                early_stopping=True,
                            )[0]['summary_text']
                            chunk_summaries.append(chunk_summary)
                            broadcast_chunk_summary(room_id, chunk_summary, idx + 1)
                            logger.info(f"Fallback chunk {idx + 1} summary (t5-small): {chunk_summary[:100]}...")
                        except Exception as e2:
                            logger.error(f"Failed fallback summarization for chunk {idx + 1}: {str(e2)}")
                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                return JsonResponse({'success': False, 'message': f"Failed to summarize chunk {idx + 1} even with fallback: {str(e2)}."})
                            messages.error(request, f"Failed to summarize chunk {idx + 1} even with fallback: {str(e2)}.")
                            return redirect('group_chat', room_id=room_id)

                if len(chunks) > 1:
                    combined_summary_text = " ".join(chunk_summaries)
                    tokens = tokenizer(combined_summary_text, truncation=True, max_length=max_input_length, return_tensors="pt", return_length=True)
                    combined_token_count = tokens['length'].item()
                    max_length = min(150, max(50, combined_token_count // 3))
                    if combined_token_count < max_length:
                        max_length = max(10, combined_token_count // 2)
                    min_length = min(30, max_length - 10)

                    try:
                        summary = summarizer(
                            combined_summary_text,
                            max_length=max_length,
                            min_length=min_length,
                            do_sample=False,
                            num_beams=4,
                            early_stopping=True,
                        )[0]['summary_text']
                        logger.info(f"Final combined summary: {summary[:100]}...")
                    except Exception as e:
                        logger.error(f"Error summarizing combined text: {str(e)} with text sample: {combined_summary_text[:100]}...")
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'message': f"Failed to summarize combined text: {str(e)}."})
                        messages.error(request, f"Failed to summarize combined text: {str(e)}. Falling back to t5-small.")
                        try:
                            fallback_tokenizer = AutoTokenizer.from_pretrained("t5-small")
                            fallback_summarizer = pipeline("summarization", model="t5-small", tokenizer=fallback_tokenizer, device=device)
                            summary = fallback_summarizer(
                                combined_summary_text,
                                max_length=max_length,
                                min_length=min_length,
                                do_sample=False,
                                num_beams=4,
                                early_stopping=True,
                            )[0]['summary_text']
                            logger.info(f"Fallback final combined summary (t5-small): {summary[:100]}...")
                        except Exception as e2:
                            logger.error(f"Failed fallback summarization for combined text: {str(e2)}")
                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                return JsonResponse({'success': False, 'message': f"Failed to summarize combined text even with fallback: {str(e2)}."})
                            messages.error(request, f"Failed to summarize combined text even with fallback: {str(e2)}.")
                            return redirect('group_chat', room_id=room_id)
                else:
                    summary = chunk_summaries[0]

                try:
                    kw_model = KeyBERT(model=SentenceTransformer('all-MiniLM-L6-v2'))
                    key_points = kw_model.extract_keywords(
                        summary,
                        keyphrase_ngram_range=(1, 2),
                        stop_words='english',
                        top_n=5,
                        use_mmr=True,
                        diversity=0.7
                    )
                    key_points = [keyword for keyword, score in key_points]
                    logger.info(f"Key points extracted with KeyBERT: {key_points}")
                except Exception as e:
                    logger.error(f"Error extracting key points with KeyBERT: {str(e)}")
                    key_points = [sentence.strip() for sentence in summary.split('. ') if sentence]

                resources = get_resources(key_points, summary)
                logger.info(f"Generated resources during POST: {resources}")

                summary_obj = Summary.objects.create(
                    room=room,
                    uploader=user,
                    pdf_name=original_filename,
                    actual_file_name=filename,
                    summary_text=summary,
                    key_points=json.dumps(key_points)
                )

                broadcast_summary(room_id, summary, user.name, original_filename)

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'PDF uploaded and summary generated.'})
                return redirect('group_chat', room_id=room_id)

        all_key_points = [
            json.loads(summary.key_points) if summary.key_points else []
            for summary in room.summaries.all()
        ]
        flattened_key_points = []
        seen_key_points = set()
        for sublist in all_key_points:
            for point in sublist:
                if point not in seen_key_points:
                    seen_key_points.add(point)
                    flattened_key_points.append(point)
        logger.info(f"Flattened key points: {flattened_key_points}")

        if summaries.exists():
            latest_summary = summaries.first()
            latest_key_points = json.loads(latest_summary.key_points) if latest_summary.key_points else []
            resources = get_resources(latest_key_points, latest_summary.summary_text)
            logger.info(f"Regenerated resources for latest summary: {resources}")
        else:
            resources = []

        rankings = []
        if is_ranking_session:
            user_scores = {}
            participants = room.participants.all()
            for participant in list(participants) + [room.creator]:
                responses = QuizResponse.objects.filter(quiz__room=room, user=participant)
                score = sum(1 for r in responses if r.selected_answer == r.quiz.correct_answer)
                user_scores[participant.name] = score
            rankings = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'room_{room.id}',
                {
                    'type': 'broadcast_ranking',
                    'rankings': rankings,
                }
            )

        quiz_selected_answers = {response.quiz.id: response.selected_answer for response in quiz_responses}

        context = {
            'room': room,
            'user': user,
            'user_id': user.id,
            'can_access_chat': can_access_chat,
            'chat_messages': chat_messages,
            'summaries': summaries,
            'key_points': flattened_key_points,
            'resources': resources,
            'quizzes': quizzes,
            'quiz_responses': quiz_responses,
            'quiz_selected_answers': quiz_selected_answers,
            'is_study_session': is_study_session,
            'is_quiz_session': is_quiz_session,
            'is_ranking_session': is_ranking_session,
            'rankings': rankings if is_ranking_session else [],
            'total_members': room.participants.count() + 1,
            'participants': room.participants.all(),
            'csrf_token': get_token(request),
            'has_submitted_quiz': has_submitted_quiz,
            'quiz_end_timestamp': quiz_end_timestamp,
        }
        return render(request, 'group_chat.html', context)

    except Room.DoesNotExist:
        messages.error(request, 'Room not found.')
        return redirect('room_dashboard')
    
def public_room_details(request, room_id):
    if 'user_email' not in request.session:
        return redirect('login')
    
    try:
        room = Room.objects.get(id=room_id, visibility='public')
        user = User.objects.get(email=request.session['user_email'])
        if user not in room.participants.all():
            messages.error(request, 'You must join this room first.')
            return redirect('public_rooms')
        context = {'room': room}
        return render(request, 'public_room_details.html', context)
    except Room.DoesNotExist:
        messages.error(request, 'Public room not found.')
        return redirect('dashboard')

from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from .forms import CustomPasswordResetForm, CustomSetPasswordForm

class PasswordResetView(PasswordResetView):
    template_name = 'password_reset.html'
    form_class = CustomPasswordResetForm
    email_template_name = 'password_reset_email.html'
    success_url = '/password-reset/done/'

class PasswordResetDoneView(PasswordResetDoneView):
    template_name = 'password_reset_done.html'

class PasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'password_reset_confirm.html'
    form_class = CustomSetPasswordForm
    success_url = '/password-reset-complete/'

class PasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'password_reset_complete.html'

def password_recovery(request):
    if request.method == 'POST':
        form = PasswordRecoveryForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
                otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
                OTP.objects.create(email=email, otp=otp)

                send_mail(
                    'OTP for Password Recovery',
                    f'Your OTP is {otp}',
                    settings.EMAIL_HOST_USER,
                    [email],
                    fail_silently=False,
                )

                return redirect('password_recovery_otp')
            except User.DoesNotExist:
                form.add_error('email', 'Email not found.')
    else:
        form = PasswordRecoveryForm()
    return render(request, 'password_recovery.html', {'form': form})

def password_recovery_otp(request):
    if request.method == 'POST':
        form = PasswordRecoveryOTPForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            try:
                otp_record = OTP.objects.get(otp=otp)
                request.session['recovery_email'] = otp_record.email
                otp_record.delete()
                return redirect('new_password')
            except OTP.DoesNotExist:
                form.add_error('otp', 'Invalid OTP')
    else:
        form = PasswordRecoveryOTPForm()
    return render(request, 'password_recovery_otp.html', {'form': form})

def new_password(request):
    if request.method == 'POST':
        form = NewPasswordForm(request.POST)
        if form.is_valid():
            new_password1 = form.cleaned_data['new_password1']
            new_password2 = form.cleaned_data['new_password2']
            if new_password1 == new_password2:
                email = request.session.get('recovery_email')
                user = User.objects.get(email=email)
                user.password = new_password1
                user.save()
                del request.session['recovery_email']
                return redirect('login')
            else:
                form.add_error('new_password2', 'Passwords do not match')
    else:
        form = NewPasswordForm()
    return render(request, 'new_password.html', {'form': form})

@require_POST
def join_public_room(request, room_id):
    if 'user_email' not in request.session:
        return redirect('login')
    
    user = User.objects.get(email=request.session['user_email'])
    try:
        room = Room.objects.get(id=room_id, visibility='public')
        if user in room.participants.all():
            messages.info(request, 'You are already a member of this room.')
        else:
            room.participants.add(user)
            messages.success(request, f'Joined {room.title} successfully!')
        return redirect('public_room_details', room_id=room.id)
    except Room.DoesNotExist:
        messages.error(request, 'Public room not found.')
        return redirect('dashboard')

@require_POST
def submit_quiz(request, room_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=400)

    if 'user_email' not in request.session:
        return JsonResponse({'success': False, 'message': 'User not logged in.'}, status=401)

    try:
        room = Room.objects.get(id=room_id)
        user = User.objects.get(email=request.session['user_email'])

        if user not in room.participants.all() and room.creator != user:
            return JsonResponse({'success': False, 'message': 'You are not authorized to submit a quiz for this room.'}, status=403)

        quizzes = Quiz.objects.filter(room=room)
        if not quizzes.exists():
            return JsonResponse({'success': False, 'message': 'No quizzes available for this room.'}, status=400)

        existing_responses = QuizResponse.objects.filter(room=room, user=user)
        if existing_responses.count() >= quizzes.count():
            return JsonResponse({'success': False, 'message': 'You have already submitted the quiz.'}, status=400)

        for quiz in quizzes:
            answer_key = f'quiz_{quiz.id}'
            selected_answer = request.POST.get(answer_key)
            if not selected_answer:
                return JsonResponse({'success': False, 'message': 'Please answer all questions.'}, status=400)

            QuizResponse.objects.update_or_create(
                quiz=quiz,
                user=user,
                room=room,
                defaults={'selected_answer': selected_answer}
            )
            logger.info(f"Saved quiz response for user {user.name}, quiz {quiz.id}, answer {selected_answer}")

        return JsonResponse({'success': True, 'message': 'Quiz submitted successfully.'})

    except Room.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Room not found.'}, status=404)
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)
    except Exception as e:
        logger.error(f"Error in submit_quiz: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': f'Error submitting quiz: {str(e)}'}, status=500)


@require_POST
def upload_note(request):
    if 'user_email' not in request.session:
        return JsonResponse({'success': False, 'message': 'User not logged in.'}, status=401)
    
    user = User.objects.get(email=request.session['user_email'])
    title = request.POST.get('title')
    department = request.POST.get('department')
    course = request.POST.get('course')
    topic = request.POST.get('topic')
    file = request.FILES.get('file')
    
    if not all([title, department, course, topic, file]):
        return JsonResponse({'success': False, 'message': 'All fields are required.'})
    
    if not file.name.endswith('.pdf'):
        return JsonResponse({'success': False, 'message': 'Only PDF files are allowed.'})
    
    note = Note.objects.create(
        uploader=user,
        title=title,
        department=department,
        course=course,
        topic=topic,
        file=file
    )
    
    return JsonResponse({'success': True, 'message': 'Note uploaded successfully!'})

@require_POST
def add_review(request):
    if 'user_email' not in request.session:
        return JsonResponse({'success': False, 'message': 'User not logged in.'}, status=401)
    
    user = User.objects.get(email=request.session['user_email'])
    note_id = request.POST.get('note_id')
    comment = request.POST.get('comment')
    rating = request.POST.get('rating')
    
    try:
        note = Note.objects.get(id=note_id)
        if NoteReview.objects.filter(note=note, reviewer=user).exists():
            return JsonResponse({'success': False, 'message': 'You have already reviewed this note.'})
        
        NoteReview.objects.create(
            note=note,
            reviewer=user,
            comment=comment,
            rating=rating
        )
        return JsonResponse({'success': True, 'message': 'Review added successfully!'})
    except Note.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Note not found.'})

def filter_notes(request):
    # Get filter parameters from the request
    dept = request.GET.get('dept', '').strip()
    course = request.GET.get('course', '').strip()
    topic = request.GET.get('topic', '').strip()

    # Log the received parameters
    logger.info(f"Filtering notes with: dept={dept}, course={course}, topic={topic}")

    # Start with all notes
    notes = Note.objects.all()

    # Apply filters if provided (case-insensitive)
    if dept:
        notes = notes.filter(department__iexact=dept)
    if course:
        notes = notes.filter(course__iexact=course)
    if topic:
        notes = notes.filter(topic__iexact=topic)

    # Log the number of notes after filtering
    logger.info(f"Found {notes.count()} notes after filtering")

    # Render the filtered notes to HTML
    notes_html = render_to_string('notes_list.html', {'notes': notes})

    # Return the HTML as JSON
    return JsonResponse({
        'notes_html': notes_html
    })

def download_note(request, note_id):
    try:
        note = Note.objects.get(id=note_id)
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Increment download count
        note.download_count += 1
        note.save()
        
        if is_ajax:
            return JsonResponse({
                'success': True,
                'download_count': note.download_count
            })
        
        # Serve the file
        response = FileResponse(note.file.open('rb'), as_attachment=True, filename=note.file.name.split('/')[-1])
        return response
    except Note.DoesNotExist:
        if is_ajax:
            return JsonResponse({'success': False, 'message': 'Note not found'}, status=404)
        messages.error(request, 'Note not found')
        return redirect('dashboard')

@never_cache
def study_partners(request):
    try:
        # Fetch the user from the session
        user_email = request.session.get('user_email')
        logger.debug(f"Session data in study_partners: {request.session.items()}")
        if not user_email:
            logger.warning("No user_email found in session for study_partners")
            messages.error(request, "Please log in to access study partners.")
            return redirect('login')

        user = User.objects.filter(email=user_email).first()
        if not user:
            logger.error(f"User with email {user_email} not found in study_partners")
            messages.error(request, "User not found. Please log in again.")
            return redirect('login')

        logger.info(f"User {user.name} (ID: {user.id}) accessed the study partners page")

        # Get pending study partner requests
        pending_requests = StudyPartnerRequest.objects.filter(
            Q(receiver=user, status='pending')
        ).select_related('sender')
        logger.debug(f"Pending study partner requests for user {user.name}: {pending_requests.count()}")

        # Get accepted study partners
        accepted_requests = StudyPartnerRequest.objects.filter(
            Q(sender=user, status='accepted') | Q(receiver=user, status='accepted')
        ).select_related('sender', 'receiver')
        logger.debug(f"Accepted study partners for user {user.name}: {accepted_requests.count()}")

        # Get study partner recommendations
        study_partner_recommendations = get_study_partner_recommendations(user)

        context = {
            'pending_requests': pending_requests,
            'accepted_partners': accepted_requests,
            'study_partner_recommendations': study_partner_recommendations,
        }
        return render(request, 'study_partners.html', context)

    except Exception as e:
        logger.error(f"Error rendering study partners page: {str(e)}")
        messages.error(request, "An error occurred while loading the study partners page. Please try again later.")
        return redirect('dashboard')

def get_study_partner_recommendations(user):
    logger.info(f"Generating study partner recommendations for user: {user.email}")
    logger.info(f"User attributes - Department: {user.department}, Semester: {user.semester}")

    # Exclude the current user and users who have an *accepted* study partner request
    existing_partners = StudyPartnerRequest.objects.filter(
        Q(sender=user) | Q(receiver=user),
        status='accepted'
    ).values_list('sender_id', 'receiver_id')
    existing_partner_ids = set()
    for sender_id, receiver_id in existing_partners:
        existing_partner_ids.add(sender_id)
        existing_partner_ids.add(receiver_id)
    existing_partner_ids.discard(user.id)
    logger.info(f"Existing accepted partner IDs excluded: {existing_partner_ids}")

    # Find potential study partners based on shared attributes
    potential_partners = User.objects.exclude(id=user.id).exclude(id__in=existing_partner_ids)
    logger.info(f"Found {potential_partners.count()} potential partners")

    recommendations = []
    for partner in potential_partners:
        # Ensure the user still exists
        try:
            User.objects.get(id=partner.id)
        except User.DoesNotExist:
            logger.warning(f"User {partner.name} (ID: {partner.id}) no longer exists, skipping recommendation.")
            continue

        # Log partner attributes for debugging
        logger.info(f"Evaluating partner: {partner.name} (ID: {partner.id}) - Department: {partner.department}, Semester: {partner.semester}")

        # Calculate a matching score based on shared attributes
        score = 0
        if partner.department and user.department and partner.department.lower() == user.department.lower():
            score += 2  # Higher weight for same department
            logger.info(f"Department match: {partner.department} == {user.department}")
        if partner.semester and user.semester and partner.semester == user.semester:
            score += 1  # Add to score if semesters match
            logger.info(f"Semester match: {partner.semester} == {user.semester}")

        # Fallback: Recommend based on shared room activity if no match on department or semester
        shared_room = Room.objects.filter(
            Q(creator=user) | Q(participants=user)
        ).filter(
            Q(creator=partner) | Q(participants=partner)
        ).exists()
        if shared_room and score == 0:
            score += 1  # Minimal score for shared room activity
            logger.info(f"Shared room found between {user.name} and {partner.name}")

        logger.info(f"Match score for {partner.name}: {score}")

        if score > 0:  # Only recommend users with a positive matching score
            recommendations.append({
                'user': partner,
                'match_score': score,
                'shared_attributes': {
                    'department': partner.department if partner.department and user.department and partner.department.lower() == user.department.lower() else None,
                    'semester': partner.semester if partner.semester and user.semester and partner.semester == user.semester else None,
                    'shared_room': shared_room,
                }
            })

    # Sort recommendations by match score (highest first)
    recommendations.sort(key=lambda x: x['match_score'], reverse=True)

    # Limit to top 5 recommendations
    recommendations = recommendations[:5]

    logger.info(f"Found {len(recommendations)} study partner recommendations for {user.email}")
    for rec in recommendations:
        logger.info(f"Recommending user: {rec['user'].name} (ID: {rec['user'].id}) with match score: {rec['match_score']}")

    return recommendations

        # views.py
@require_POST
def send_study_partner_request(request):
    try:
        # Fetch the user from the session
        user_email = request.session.get('user_email')
        logger.debug(f"Session data in send_study_partner_request: {request.session.items()}")
        if not user_email:
            logger.warning("No user_email found in session for send_study_partner_request")
            return JsonResponse({'success': False, 'message': 'You must be logged in to send a request.'}, status=401)

        user = User.objects.filter(email=user_email).first()
        if not user:
            logger.error(f"User with email {user_email} not found in send_study_partner_request")
            return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

        logger.debug(f"User fetched in send_study_partner_request: {user.name} (ID: {user.id})")

        receiver_id = request.POST.get('receiver_id')
        if not receiver_id:
            logger.error("No receiver_id provided in send_study_partner_request")
            return JsonResponse({'success': False, 'message': 'Receiver ID is required.'}, status=400)

        receiver = User.objects.filter(id=receiver_id).first()
        if not receiver:
            logger.error(f"Receiver with ID {receiver_id} not found")
            return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

        if receiver == user:
            logger.warning(f"User {user.name} attempted to send a request to themselves")
            return JsonResponse({'success': False, 'message': 'You cannot send a request to yourself.'}, status=400)

        # Check for existing requests (pending or accepted)
        existing_request = StudyPartnerRequest.objects.filter(
            Q(sender=user, receiver=receiver) | Q(sender=receiver, receiver=user),
            status__in=['pending', 'accepted']
        ).first()

        if existing_request:
            if existing_request.status == 'pending':
                logger.info(f"Pending request already exists between {user.name} and {receiver.name}")
                return JsonResponse({'success': False, 'message': 'A pending request already exists.'}, status=400)
            elif existing_request.status == 'accepted':
                logger.info(f"Users {user.name} and {receiver.name} are already study partners")
                return JsonResponse({'success': False, 'message': 'You are already study partners.'}, status=400)

        # Create a new study partner request
        study_partner_request = StudyPartnerRequest.objects.create(
            sender=user,
            receiver=receiver,
            status='pending'
        )
        logger.info(f"Study partner request sent from {user.name} to {receiver.name} (Request ID: {study_partner_request.id})")

        return JsonResponse({'success': True, 'message': 'Study partner request sent successfully!'})

    except Exception as e:
        logger.error(f"Error sending study partner request: {str(e)}")
        return JsonResponse({'success': False, 'message': 'An error occurred while sending the request.'}, status=500)

@require_POST
def handle_study_partner_request(request):
    if 'user_email' not in request.session:
        return JsonResponse({'success': False, 'message': 'User not logged in.'}, status=401)
    
    user = User.objects.get(email=request.session['user_email'])
    request_id = request.POST.get('request_id')
    action = request.POST.get('action')  # 'accept' or 'reject'

    try:
        study_request = StudyPartnerRequest.objects.get(id=request_id, receiver=user)
        if action == 'accept':
            study_request.status = 'accepted'
            study_request.save()
            return JsonResponse({'success': True, 'message': 'Request accepted!'})
        elif action == 'reject':
            study_request.status = 'rejected'
            study_request.save()
            return JsonResponse({'success': True, 'message': 'Request rejected!'})
        else:
            return JsonResponse({'success': False, 'message': 'Invalid action.'})
    except StudyPartnerRequest.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Request not found.'})
    

@require_POST
def accept_study_partner_request(request):
    try:
        # Fetch the user from the session
        user_email = request.session.get('user_email')
        logger.debug(f"Session data in accept_study_partner_request: {request.session.items()}")
        if not user_email:
            logger.warning("No user_email found in session for accept_study_partner_request")
            return JsonResponse({'success': False, 'message': 'You must be logged in to accept a request.'}, status=401)

        user = User.objects.filter(email=user_email).first()
        if not user:
            logger.error(f"User with email {user_email} not found in accept_study_partner_request")
            return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

        logger.debug(f"User fetched in accept_study_partner_request: {user.name} (ID: {user.id})")

        # Parse the request body (assuming JSON)
        import json
        logger.debug(f"Request body: {request.body}")
        data = json.loads(request.body) if request.body else {}
        request_id = data.get('request_id')

        if request_id is None:
            logger.error("No request_id provided in accept_study_partner_request")
            return JsonResponse({'success': False, 'message': 'Request ID is required.'}, status=400)

        # Ensure request_id is an integer
        try:
            request_id = int(request_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid request_id format: {request_id}")
            return JsonResponse({'success': False, 'message': 'Invalid request ID format.'}, status=400)

        logger.debug(f"Attempting to accept study partner request ID: {request_id} by user: {user.name}")

        # Fetch and update the study partner request within a transaction
        with transaction.atomic():
            study_partner_request = StudyPartnerRequest.objects.filter(
                id=request_id,
                receiver=user,
                status='pending'
            ).select_related('sender').first()

            if not study_partner_request:
                logger.error(f"Study partner request with ID {request_id} not found or not eligible for acceptance by {user.name}")
                return JsonResponse({'success': False, 'message': 'Request not found or you are not authorized to accept this request.'}, status=404)

            # Update the request status to accepted
            study_partner_request.status = 'accepted'
            study_partner_request.save()
            logger.info(f"Study partner request {request_id} accepted by {user.name} (Sender: {study_partner_request.sender.name})")

            # Prepare the partner's details to return in the response
            partner = study_partner_request.sender  # The sender is the partner being added
            profile_picture_url = partner.profile_picture.url if partner.profile_picture else None

            return JsonResponse({
                'success': True,
                'message': 'Study partner request accepted successfully!',
                'partner': {
                    'name': partner.name,
                    'department': partner.department or "N/A",
                    'semester': partner.semester or "Not specified",
                    'profile_picture_url': profile_picture_url
                }
            })

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON in accept_study_partner_request: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request data.'}, status=400)
    except Exception as e:
        logger.error(f"Error accepting study partner request: {str(e)}")
        return JsonResponse({'success': False, 'message': 'An error occurred while accepting the request.'}, status=500)
@require_POST
def reject_study_partner_request(request):
    try:
        # Fetch the user from the session
        user_email = request.session.get('user_email')
        logger.debug(f"Session data in reject_study_partner_request: {request.session.items()}")
        if not user_email:
            logger.warning("No user_email found in session for reject_study_partner_request")
            return JsonResponse({'success': False, 'message': 'You must be logged in to reject a request.'}, status=401)

        user = User.objects.filter(email=user_email).first()
        if not user:
            logger.error(f"User with email {user_email} not found in reject_study_partner_request")
            return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

        logger.debug(f"User fetched in reject_study_partner_request: {user.name} (ID: {user.id})")

        # Parse the request body (assuming JSON)
        import json
        logger.debug(f"Request body: {request.body}")
        data = json.loads(request.body) if request.body else {}
        request_id = data.get('request_id')

        if request_id is None:
            logger.error("No request_id provided in reject_study_partner_request")
            return JsonResponse({'success': False, 'message': 'Request ID is required.'}, status=400)

        # Ensure request_id is an integer
        try:
            request_id = int(request_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid request_id format: {request_id}")
            return JsonResponse({'success': False, 'message': 'Invalid request ID format.'}, status=400)

        logger.debug(f"Attempting to reject study partner request ID: {request_id} by user: {user.name}")

        # Fetch the study partner request
        study_partner_request = StudyPartnerRequest.objects.filter(
            id=request_id,
            receiver=user,
            status='pending'
        ).first()

        if not study_partner_request:
            logger.error(f"Study partner request with ID {request_id} not found or not eligible for rejection by {user.name}")
            return JsonResponse({'success': False, 'message': 'Request not found or you are not authorized to reject this request.'}, status=404)

        # Update the request status to rejected
        study_partner_request.status = 'rejected'
        study_partner_request.save()
        logger.info(f"Study partner request {request_id} rejected by {user.name} (Sender: {study_partner_request.sender.name})")

        return JsonResponse({'success': True, 'message': 'Study partner request rejected successfully!'})

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON in reject_study_partner_request: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request data.'}, status=400)
    except Exception as e:
        logger.error(f"Error rejecting study partner request: {str(e)}")
        return JsonResponse({'success': False, 'message': 'An error occurred while rejecting the request.'}, status=500)


def offline_view(request):
    return render(request, 'offline.html')