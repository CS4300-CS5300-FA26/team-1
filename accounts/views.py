from typing import cast

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters

from core.models import UserProfile

from . import throttle
from .forms import EMAIL_TAKEN_MESSAGE, LoginForm, RegisterForm

# Created in migration accounts/0002_unique_email_index.
EMAIL_UNIQUE_INDEX = 'auth_user_email_lower_uniq'
USERNAME_TAKEN_MESSAGE = 'A user with that username already exists.'


class CustomLoginView(LoginView):
    """Log in, then send users who haven't finished the onboarding checklist to it."""

    authentication_form = LoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        # Count the attempt before authenticate() runs (atomically, so parallel requests share
        # the limit); a blocked client can't keep guessing passwords.
        retry_after = throttle.acquire_login(request.POST.get('username', ''), throttle.client_ip(request))
        if retry_after:
            form = self.get_form()
            form.cleaned_data = {}  # add_error() needs it on a form that was never validated
            form.add_error(None, throttle.THROTTLED_MESSAGE)
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response['Retry-After'] = str(retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        throttle.release_login(self.request.POST.get('username', ''), throttle.client_ip(self.request))
        return super().form_valid(form)

    def get_success_url(self):
        # LoginView only gets here after login(), so the user is real, not AnonymousUser.
        user = cast(User, self.request.user)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.onboarding_completed:
            return reverse('onboarding')
        return super().get_success_url()  # ?next= if present, else LOGIN_REDIRECT_URL ('dashboard')


@sensitive_post_parameters('password1', 'password2')  # keep passwords out of error reports
def register(request):
    """Create an account, log the new user in, and send them to the onboarding questionnaire."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        ip = throttle.client_ip(request)
        retry_after = throttle.acquire_register(ip)
        if retry_after:
            form = RegisterForm()
            form.cleaned_data = {}  # add_error() needs it on a form that was never validated
            form.add_error(None, throttle.THROTTLED_MESSAGE)
            response = render(request, 'accounts/register.html', {'form': form}, status=429)
            response['Retry-After'] = str(retry_after)
            return response

    form = RegisterForm(request.POST or None)
    user = None
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError as exc:
            # Lost a race with another sign-up; the database caught the duplicate. Say which
            # field collided, and let anything else surface instead of mislabelling it.
            # PostgreSQL and SQLite both put the violated constraint's name in the message.
            if EMAIL_UNIQUE_INDEX in str(exc):
                form.add_error('email', EMAIL_TAKEN_MESSAGE)
            elif 'username' in str(exc):
                form.add_error('username', USERNAME_TAKEN_MESSAGE)
            else:
                raise
    if user:
        # Every user needs a profile so the onboarding and dashboard views can read it.
        UserProfile.objects.get_or_create(user=user)
        # login() rotates the session key, which prevents session fixation.
        login(request, user)
        return redirect('onboarding')
    return render(request, 'accounts/register.html', {'form': form})


def after_login_url(user) -> str:
    """Where a newly logged-in user goes: onboarding until they finish it, then the dashboard."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return reverse('dashboard' if profile.onboarding_completed else 'onboarding')


@login_required
@sensitive_post_parameters('new_password1', 'new_password2')  # keep passwords out of error reports
def set_password(request):
    """Give a password to an account that has none (one created with "Sign up with Spotify").

    No current password is asked for because there isn't one; the user has just proved who they are by logging in.
    Accounts that already have a password are sent on, so this can never be used to change a password without the
    old one.
    """
    if request.user.has_usable_password():
        return redirect(after_login_url(request.user))
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # Changing the password changes the session hash; keep this session logged in (and rotate its key).
        update_session_auth_hash(request, user)
        messages.success(request, 'Password set. You can now log in with your email and password too.')
        return redirect(after_login_url(user))
    return render(request, 'accounts/set_password.html', {'form': form})
