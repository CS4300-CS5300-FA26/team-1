import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.generic import FormView

from core.models import UserProfile

from . import emails, services, throttle
from .forms import EmailRequestForm, LoginForm, RegisterForm
from .tokens import email_verification_token

logger = logging.getLogger('accounts.security')

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
    """Start a sign-up: create an inactive account and email a confirmation link (ADR-018).

    The page never says whether an email already has an account. If it does, its owner gets an email saying so, and
    the person sees the same "check your email" page either way, even when the email couldn't be sent: an error then
    would reveal accounts, because an address's email limit can be used up through "forgot password", which only sends
    for addresses with an account. Failures are logged instead. Nobody is logged in here; the confirmation link does
    that, once it proves the person controls the address.
    """
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        retry_after = throttle.acquire_register(throttle.client_ip(request))
        if retry_after:
            return _register_throttled(request, retry_after)

        # Before validation, so an expired sign-up no longer holds its username or email.
        services.prune_unconfirmed_accounts()

    form = RegisterForm(request.POST or None)
    if request.method != 'POST':
        return render(request, 'accounts/register.html', {'form': form})
    user = None
    if form.is_valid() and not User.objects.filter(email__iexact=form.cleaned_data['email']).exists():
        try:
            user = _create_unconfirmed_account(form)
        except IntegrityError as exc:
            # Lost a race with another sign-up; the database caught the duplicate. A taken email is handled like any
            # registered one below; a taken username is reported like the form's own check. PostgreSQL and SQLite
            # both put the violated constraint's name in the message.
            if EMAIL_UNIQUE_INDEX in str(exc):
                pass
            elif 'username' in str(exc):
                form.add_error('username', ValidationError(USERNAME_TAKEN_MESSAGE, code='unique'))
            else:
                raise
    if reveals_an_account(form):
        retry_after = throttle.acquire_register_probe(throttle.client_ip(request))
        if retry_after:
            # Out of answers that reveal accounts (ADR-016). Say nothing about taken usernames. With other errors,
            # show just those: the same page an unused username would get, so a deliberately bad password can't turn
            # this refusal into a yes/no answer. With none, refuse like any other throttle.
            hide_account_errors(form)
            if not form.errors:
                return _register_throttled(request, retry_after)
    if form.errors:
        return render(request, 'accounts/register.html', {'form': form})

    if user is None:
        if not emails.send_account_exists_email(request, form.cleaned_data['email']):
            logger.warning('"Account exists" email not sent; showing the usual page')
    elif not emails.send_verification_email(request, user):
        # Kept, so the person can use "send the link again" once email works; unconfirmed sign-ups expire anyway.
        logger.warning('Confirmation link for new user %s not sent; showing the usual page', user.pk)
    return redirect('verify_email_sent')


def _create_unconfirmed_account(form):
    with transaction.atomic():
        user = form.save(commit=False)
        user.is_active = False
        user.save()
        # Every user needs a profile so the onboarding and dashboard views can read it.
        UserProfile.objects.get_or_create(user=user)
    return user


def verify_email_sent(request):
    """ "Check your email", after a sign-up or a request to send the confirmation link again."""
    return render(request, 'accounts/verify_email_sent.html')


@never_cache
@require_http_methods(['GET', 'POST'])
def verify_email(request, uidb64, token):
    """Confirm an email from the link we sent. GET shows a button; only the POST activates the account and logs in.

    The extra click matters because email security scanners open links in messages; a GET that confirmed the account
    would let a scanner do it.
    """
    user = _user_from_uid(uidb64)
    if user is None or not email_verification_token.check_token(user, token):
        return render(request, 'accounts/verify_email_invalid.html', status=400)
    if request.method == 'GET':
        return render(request, 'accounts/verify_email_confirm.html', {'email': user.email})
    services.confirm_email(user)
    # login() rotates the session key, which prevents session fixation.
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, 'Your email is confirmed.')
    if not user.has_usable_password():
        # Created with "Sign up with Spotify": ask for a password before onboarding, as the Spotify flow does.
        return redirect('set_password')
    return redirect(after_login_url(user))


def resend_verification(request):
    """Send the confirmation link again to an unconfirmed sign-up.

    Answers the same way whether or not the address has an unconfirmed sign-up, and whether or not the email went out:
    a different answer only when we tried to send would reveal which addresses have accounts (ADR-018). Failures are
    logged instead.
    """
    form = EmailRequestForm(request.POST or None)
    if request.method == 'POST':
        response = _email_request_throttled(request, form, 'accounts/resend_verification.html')
        if response:
            return response
        if form.is_valid():
            services.prune_unconfirmed_accounts()
            user = User.objects.filter(email__iexact=form.cleaned_data['email'], is_active=False).first()
            via_spotify = user is not None and _has_spotify(user)
            if user is not None and not emails.send_verification_email(request, user, via_spotify=via_spotify):
                logger.warning('Confirmation link for user %s not sent; showing the usual page', user.pk)
            return redirect('verify_email_sent')
    return render(request, 'accounts/resend_verification.html', {'form': form})


class PasswordResetView(FormView):
    """Email a password reset link (Django's reset tokens, sent through Resend).

    A plain FormView rather than Django's PasswordResetView, whose form and email sending are all replaced here.

    Unlike Django's default, accounts without a password (Spotify sign-ups) and unconfirmed accounts can reset too:
    proving control of the inbox is what matters, and for an unconfirmed account it also confirms the email.

    Answers the same way whether or not the address has an account, and whether or not the email went out: a
    different answer only when we tried to send would reveal which addresses have accounts (ADR-018). Failures are
    logged instead.
    """

    form_class = EmailRequestForm
    template_name = 'accounts/password_reset.html'
    success_url = reverse_lazy('password_reset_done')

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        response = _email_request_throttled(request, form, self.template_name)
        return response or super().post(request, *args, **kwargs)

    def form_valid(self, form):
        services.prune_unconfirmed_accounts()
        user = User.objects.filter(email__iexact=form.cleaned_data['email']).first()
        if user is not None and not emails.send_password_reset_email(self.request, user):
            logger.warning('Password reset link for user %s not sent; showing the usual page', user.pk)
        return redirect(self.success_url)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Choose a new password from the emailed link. Django moves the token out of the URL before the form shows."""

    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')

    def form_valid(self, form):
        user = cast(User, self.user)  # Django only shows the form, and so only calls this, for a valid link
        was_confirmed = user.is_active
        response = super().form_valid(form)
        if not was_confirmed:
            services.claim_unconfirmed_account(user)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'


def _email_request_throttled(request, form, template_name):
    """The per-IP limit on "forgot password" and "resend confirmation" (ADR-018), or None if the request may go on."""
    retry_after = throttle.acquire_email_request(throttle.client_ip(request))
    if not retry_after:
        return None
    form.cleaned_data = {}  # add_error() needs it on a form that was never validated
    form.add_error(None, throttle.THROTTLED_MESSAGE)
    response = render(request, template_name, {'form': form}, status=429)
    response['Retry-After'] = str(retry_after)
    return response


def _user_from_uid(uidb64):
    try:
        return User.objects.filter(pk=force_str(urlsafe_base64_decode(uidb64))).first()
    except (TypeError, ValueError, OverflowError):
        return None


def _has_spotify(user) -> bool:
    from spotify.models import SpotifyAccount  # spotify imports accounts, so import here, not at module level

    return SpotifyAccount.objects.filter(user=user).exists()


def _register_throttled(request, retry_after: int):
    form = RegisterForm()
    form.cleaned_data = {}  # add_error() needs it on a form that was never validated
    form.add_error(None, throttle.THROTTLED_MESSAGE)
    response = render(request, 'accounts/register.html', {'form': form}, status=429)
    response['Retry-After'] = str(retry_after)
    return response


# The errors that say a username is taken; Django's UserCreationForm marks them with the "unique" code. Only these
# count against `register_taken` (ADR-016). The form never says an email is taken (ADR-018).
ACCOUNT_ERRORS = (('username', 'unique'),)


def reveals_an_account(form) -> bool:
    """Whether the form says a username is taken, which tells the caller that an account exists."""
    return any(form.has_error(field, code) for field, code in ACCOUNT_ERRORS)


def hide_account_errors(form) -> None:
    """Drop the errors that say a username is taken, keeping every other error."""
    for field, code in ACCOUNT_ERRORS:
        errors = form.errors.get(field)
        if errors is not None:
            # In place, so the list keeps the field_id Django uses to link errors to their input (aria-describedby).
            errors.data = [error for error in errors.data if getattr(error, 'code', None) != code]
            if not errors:
                del form.errors[field]


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
