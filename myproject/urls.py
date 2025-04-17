from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from accounts import views
from django.views.generic import TemplateView
from django.views.static import serve
from django.urls import re_path
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('signup/', views.signup, name='signup'),
    path('otp_verification/', views.otp_verification, name='otp_verification'),
    path('login/', views.login, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('create-room/', views.create_room, name='create_room'),
    path('delete-room/<int:room_id>/', views.delete_room, name='delete_room'),
    path('join-public-room/<int:room_id>/', views.join_public_room, name='join_public_room'),
    path('join-room/', views.join_room_base, name='join_room_base'),
    path('public-rooms/', views.public_rooms, name='public_rooms'),
    path('private-room/<int:room_id>/', views.private_room, name='private_room'),
    path('room-dashboard/', views.room_dashboard, name='room_dashboard'),
    path('public-room-details/<int:room_id>/', views.public_room_details, name='public_room_details'),
    path('leave-room/<int:room_id>/', views.leave_room, name='leave_room'),
    path('group-chat/<int:room_id>/', views.group_chat, name='group_chat'),
    path('profile-settings/', views.profile_settings, name='profile_settings'),
    path('update-profile/', views.update_profile, name='update_profile'),
    path('password-reset/', views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset-complete/', views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('password-recovery/', views.password_recovery, name='password_recovery'),
    path('password-recovery-otp/', views.password_recovery_otp, name='password_recovery_otp'),
    path('new-password/', views.new_password, name='new_password'),
    path('submit-quiz/<int:room_id>/', views.submit_quiz, name='submit_quiz'),
    path('upload_note/', views.upload_note, name='upload_note'),
    path('add_review/', views.add_review, name='add_review'),
    path('filter_notes/', views.filter_notes, name='filter_notes'),
    path('download_note/<int:note_id>/', views.download_note, name='download_note'),
    path('send_study_partner_request/', views.send_study_partner_request, name='send_study_partner_request'),
    path('study_partners/', views.study_partners, name='study_partners'),  # This line is causing the error
    path('handle_study_partner_request/', views.handle_study_partner_request, name='handle_study_partner_request'),
    path('accept-study-partner-request/', views.accept_study_partner_request, name='accept_study_partner_request'),
    path('reject-study-partner-request/', views.reject_study_partner_request, name='reject_study_partner_request'),
    path('offline/', views.offline_view, name='offline'),

    # path('group-chat/<int:room_id>/submit-quiz/', views.submit_quiz, name='submit_quiz'),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Serve media files in production
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]