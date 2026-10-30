from typing import cast

from django.contrib.auth import login
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
