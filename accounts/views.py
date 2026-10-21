from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from .forms import RegisterForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.urls import reverse
from .forms import LoginForm
from core.models import UserProfile


class CustomLoginView(LoginView):
    """Log in, then send users who haven't finished the onboarding checklist to it."""

    authentication_form = LoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        if not profile.onboarding_completed:
            return reverse('onboarding')
        return super().get_success_url()  # ?next= if present, else LOGIN_REDIRECT_URL ('home')

@sensitive_post_parameters('password1', 'password2')  # keep passwords out of error reports
def register(request):
    """Create an account, log the new user in, and send them to the onboarding questionnaire."""
    if request.user.is_authenticated:
        return redirect('home')

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        UserProfile.objects.get_or_create(user=user)   # the missing line
        # login() rotates the session key, which prevents session fixation.
        login(request, user)
        return redirect('onboarding')
    return render(request, 'accounts/register.html', {'form': form})