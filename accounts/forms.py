from django import forms
from .models import Review, User
from .models import Room
from datetime import datetime

class SignUpForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['name', 'email', 'password']
        widgets = {
            'password': forms.PasswordInput(),
        }

class OTPVerificationForm(forms.Form):
    otp = forms.CharField(max_length=6, required=True)

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['name', 'password', 'department', 'semester', 'profile_picture']
        widgets = {
            'password': forms.PasswordInput(),
        }

class CustomPasswordResetForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'class': 'form-control'})
    )

class CustomSetPasswordForm(forms.Form):
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'form-control'}),
        strip=False,
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'form-control'}),
        strip=False,
    )

class PasswordRecoveryForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'class': 'form-control'})
    )

class PasswordRecoveryOTPForm(forms.Form):
    otp = forms.CharField(max_length=6, required=True)

class NewPasswordForm(forms.Form):
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'form-control'}),
        strip=False,
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'form-control'}),
        strip=False,
    )

class RoomForm(forms.ModelForm):
    time = forms.CharField(widget=forms.TextInput(attrs={'type': 'time'}))

    class Meta:
        model = Room
        fields = ['title', 'course', 'department', 'date', 'time', 'visibility']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_time(self):
        time_str = self.cleaned_data['time']
        try:
            # If the browser sends time in 24-hour format (e.g., "12:43")
            return datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            # If the time is in 12-hour format with AM/PM (e.g., "12:43 PM")
            try:
                parsed_time = datetime.strptime(time_str, '%I:%M %p')
                return parsed_time.time()
            except ValueError:
                raise forms.ValidationError("Invalid time format. Use HH:MM or HH:MM AM/PM.")
            

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['text', 'rating']
        widgets = {
            'rating': forms.Select(choices=Review.RATING_CHOICES)
        }            