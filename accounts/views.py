from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters

from .forms import RegisterForm


@sensitive_post_parameters('password1', 'password2')  # keep passwords out of error reports
def register(request):
    """Create an account, log the new user in, and send them to the onboarding questionnaire."""
    if request.user.is_authenticated:
        return redirect('home')

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # login() rotates the session key, which prevents session fixation.
        login(request, user)
        return redirect('onboarding')
    return render(request, 'accounts/register.html', {'form': form})