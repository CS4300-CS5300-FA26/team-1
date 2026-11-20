from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    # Logout only accepts POST (a link would 405), so templates use a small form.
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    # For accounts created without a password (Sign up with Spotify, ADR-010).
    path('password/set/', views.set_password, name='set_password'),
    # Email confirmation (ADR-018).
    path('verify/sent/', views.verify_email_sent, name='verify_email_sent'),
    path('verify/resend/', views.resend_verification, name='resend_verification'),
    path('verify/<uidb64>/<token>/', views.verify_email, name='verify_email'),
    # Password reset (ADR-018).
    path('password/reset/', views.PasswordResetView.as_view(), name='password_reset'),
    path('password/reset/sent/', views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password/reset/<uidb64>/<token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password/reset/done/', views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
