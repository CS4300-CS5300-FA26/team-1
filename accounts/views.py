from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters

from core.models import UserProfile

from . import throttle
from .forms import LoginForm, RegisterForm


class CustomLoginView(LoginView):
    """Log in, then send users who haven't finished the onboarding checklist to it."""

    authentication_form = LoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        # Check before authenticate() runs, so a blocked client can't keep guessing passwords.
        if throttle.login_blocked(request.POST.get('username', ''), throttle.client_ip(request)):
            form = self.get_form()
            form.cleaned_data = {}  # add_error() needs it on a form that was never validated
            form.add_error(None, throttle.THROTTLED_MESSAGE)
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response['Retry-After'] = str(throttle.retry_after('login'))
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        throttle.record_login_failure(self.request.POST.get('username', ''), throttle.client_ip(self.request))
        return super().form_invalid(form)

    def form_valid(self, form):
        throttle.clear_login_failures(self.request.POST.get('username', ''), throttle.client_ip(self.request))
        return super().form_valid(form)

    def get_success_url(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
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
        if throttle.register_blocked(ip):
            form = RegisterForm()
            form.cleaned_data = {}  # add_error() needs it on a form that was never validated
            form.add_error(None, throttle.THROTTLED_MESSAGE)
            response = render(request, 'accounts/register.html', {'form': form}, status=429)
            response['Retry-After'] = str(throttle.retry_after('register'))
            return response
        throttle.record_register_attempt(ip)

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # Every user needs a profile so the onboarding and dashboard views can read it.
        UserProfile.objects.get_or_create(user=user)
        # login() rotates the session key, which prevents session fixation.
        login(request, user)
        return redirect('onboarding')
    return render(request, 'accounts/register.html', {'form': form})
