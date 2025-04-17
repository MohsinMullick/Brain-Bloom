# models.py
from django.db import models
from django.core.validators import EmailValidator
from django.utils import timezone
import pytz
from datetime import datetime, timedelta
import logging
import json
from django.db.models import CheckConstraint, Q
logger = logging.getLogger(__name__)

class User(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, validators=[EmailValidator(message="Enter a valid @northsouth.edu email.", code="invalid_email")])
    password = models.CharField(max_length=100)  # Should be hashed in production
    is_verified = models.BooleanField(default=False)
    department = models.CharField(max_length=100, blank=True, null=True)
    semester = models.CharField(max_length=50, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    def __str__(self):
        return self.email

class OTP(models.Model):
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email

class Room(models.Model):
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
    ]
    
    title = models.CharField(max_length=100)
    course = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    topic = models.CharField(max_length=100, null=True)
    date = models.DateField()
    time = models.TimeField()
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='public')
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_rooms')
    participants = models.ManyToManyField(User, related_name='joined_rooms')
    code = models.CharField(max_length=10, blank=True, null=True)
    is_public = models.BooleanField(default=True)



    def get_start_datetime(self):
        """Combine date and time into a timezone-aware datetime object."""
        naive_datetime = timezone.datetime.combine(self.date, self.time)
        return timezone.make_aware(naive_datetime)
    def get_end_time(self):
        tz = pytz.timezone('Asia/Dhaka')
        naive_start_datetime = datetime.combine(self.date, self.time)
        start_datetime = tz.localize(naive_start_datetime)
        end_time = start_datetime + timedelta(minutes=20)
        logger.info(f"Room {self.title} - Start: {start_datetime}, End: {end_time}")
        return end_time

    def is_expired(self):
        tz = pytz.timezone('Asia/Dhaka')
        current_time = timezone.now().astimezone(tz)
        end_time = self.get_end_time()
        is_expired = current_time > end_time
        logger.info(f"Room {self.title} - Current time: {current_time}, End time: {end_time}, Expired: {is_expired}")
        return is_expired

    class Meta:
        unique_together = ('title', 'date', 'time', 'creator')

    def __str__(self):
        return self.title

# models.py
class Summary(models.Model):
    room = models.ForeignKey(Room, related_name='summaries', on_delete=models.CASCADE)
    uploader = models.ForeignKey(User, on_delete=models.CASCADE)
    pdf_name = models.CharField(max_length=255)  # Original filename
    actual_file_name = models.CharField(max_length=255, blank=True, null=True)  # Actual filename with UUID
    summary_text = models.TextField()
    key_points = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Summary for {self.pdf_name} by {self.uploader.name}"

    class Meta:
        constraints = [
            CheckConstraint(
                check=Q(key_points__isnull=True) | Q(key_points__regex=r'^\[.*\]$'),  # Ensures valid JSON array
                name='valid_json_key_points'
            )
        ]

    def __str__(self):
        return f"{self.pdf_name} - {self.uploader.name}"

# models.py
class ChatMessage(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)  # Allow null for AI messages
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_ai_response = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sender.name if self.sender else 'AI'}: {self.message} ({self.timestamp})"

class Quiz(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='quizzes')
    question = models.TextField()
    options = models.JSONField()  # e.g., {"A": "option1", "B": "option2", "C": "option3", "D": "option4"}
    correct_answer = models.CharField(max_length=1)  # e.g., "A", "B", "C", or "D"
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Quiz for {self.room.title}: {self.question[:50]}..."

class QuizResponse(models.Model):
    room = models.ForeignKey(Room, related_name='quiz_responses', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    selected_answer = models.CharField(max_length=1)  # e.g., "A", "B", "C", "D"
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'user', 'quiz')  # Prevent duplicate responses

    def __str__(self):
        return f"Response by {self.user.name} for quiz {self.quiz.id}"
    


    # models.py
class Note(models.Model):
    uploader = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_notes')
    title = models.CharField(max_length=200)
    department = models.CharField(max_length=100)
    course = models.CharField(max_length=100)
    topic = models.CharField(max_length=100)
    file = models.FileField(upload_to='notes/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    download_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.title} - {self.department}"

class NoteReview(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    rating = models.PositiveIntegerField(choices=[(i, i) for i in range(1, 6)])  # 1-5 rating
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('note', 'reviewer')

    def __str__(self):
        return f"Review by {self.reviewer.name} for {self.note.title}"
    

    # models.py
class StudyPartnerRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_study_requests')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_study_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('sender', 'receiver')  # Prevent duplicate requests between the same users

    def __str__(self):
        return f"{self.sender.name} -> {self.receiver.name} ({self.status})"




class Review(models.Model):
    RATING_CHOICES = [(i, i) for i in range(1, 6)]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField()
    rating = models.PositiveIntegerField(choices=RATING_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    approved = models.BooleanField(default=True)

    def __str__(self):
        return f"Review by {self.user.name} - {self.rating} stars"