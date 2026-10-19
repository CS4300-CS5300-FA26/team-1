from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import UserProfile

EMAIL_MAX_LENGTH = User._meta.get_field('username').max_length  # 150

EMAIL_TAKEN_MESSAGE = 'An account with this email is already registered.'
INVALID_LOGIN_MESSAGE = 'Invalid email or password'

#This is the sign-up sheet
class RegistrationForm(forms.Form):
    email = forms.EmailField(
        label='Email',
        max_length=EMAIL_MAX_LENGTH,
        widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email'}),
    )
    password1 = forms.CharField(
        label='Password',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label='Confirm password',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    #lowercases the email and checks if it is already taken
    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            raise ValidationError(EMAIL_TAKEN_MESSAGE, code='email_taken')
        return email
    
    #checks if the two passwords match and validates the password against Django's built-in validators
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            self.add_error('password2', ValidationError(
                "The two password fields didn't match.", code='password_mismatch'))
        elif password1:
            email = cleaned_data.get('email')
            candidate = User(username=email, email=email) if email else None
            try:
                password_validation.validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error('password1', error)
        return cleaned_data

    #creates the user and user profile in a single transaction to ensure data integrity
    def save(self):
        email = self.cleaned_data['email']
        with transaction.atomic():
            user = User.objects.create_user(
                username=email, email=email, password=self.cleaned_data['password1'])
            UserProfile.objects.create(user=user)
        return user

#This is the login form that uses email as the username
class EmailAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='Email',
        widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email'}),
    )
    error_messages = {
        'invalid_login': INVALID_LOGIN_MESSAGE,
        'inactive': INVALID_LOGIN_MESSAGE,
    }

    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()