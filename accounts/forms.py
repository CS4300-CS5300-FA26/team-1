from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

User = get_user_model()

# One generic message for every login failure (unknown user, wrong password, inactive
# account) so the login form never reveals which emails or usernames have accounts.
INVALID_LOGIN_MESSAGE = 'Invalid email or password'


EMAIL_TAKEN_MESSAGE = 'An account with this email already exists.'


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
            raise forms.ValidationError(EMAIL_TAKEN_MESSAGE)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # AuthenticationForm sets maxlength to User.username's 150 characters, so the browser
        # won't accept a longer value, but people can also log in with an email, which may
        # be up to User.email's 254.
        email_max_length = User._meta.get_field('email').max_length
        self.fields['username'].max_length = email_max_length  # type: ignore[attr-defined]
        self.fields['username'].widget.attrs['maxlength'] = email_max_length

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        if '@' in value:
            # Emails are unique (case-insensitively) at registration, so one match means
            # we know whose account this is; swap in their username for authenticate().
            matches = list(User.objects.filter(email__iexact=value)[:2])
            if len(matches) == 1:
                return matches[0].get_username()
        return value
