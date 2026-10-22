from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

User = get_user_model()

# One generic message for every login failure (unknown user, wrong password, inactive
# account) so the login form never reveals which emails or usernames have accounts.
INVALID_LOGIN_MESSAGE = 'Invalid email or password'


def no_at_sign(value):
    """Usernames may not contain "@" so a username can never be mistaken for an email."""
    if '@' in value:
        raise ValidationError('Usernames cannot contain "@". Put your email in the email field.')


class RegisterForm(UserCreationForm):
    """Sign-up form: Django's UserCreationForm plus a required, unique email."""

    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].validators.append(no_at_sign)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email


class LoginForm(AuthenticationForm):
    """Log in with an email address (or a username) and a password.

    Every failure shows the same message, INVALID_LOGIN_MESSAGE.
    """

    username = forms.CharField(
        label='Email or username',
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}),
    )

    error_messages = {
        'invalid_login': INVALID_LOGIN_MESSAGE,
        'inactive': INVALID_LOGIN_MESSAGE,
    }

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        if '@' in value:
            # Emails are unique (case-insensitively) at registration, so one match means
            # we know whose account this is; swap in their username for authenticate().
            matches = list(User.objects.filter(email__iexact=value)[:2])
            if len(matches) == 1:
                return matches[0].get_username()
        return value