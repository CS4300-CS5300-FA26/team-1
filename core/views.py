from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import OnboardingForm
from .models import UserProfile


def home(request):
    return render(request, 'core/home.html')


@login_required
def onboarding(request):
    """Onboarding questionnaire. Saves the answers, marks onboarding done, goes to the dashboard."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.onboarding_completed:
        return redirect('dashboard')

    # A bound form that fails validation re-renders with the user's other answers filled in.
    form = OnboardingForm(request.POST or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        profile = form.save(commit=False)
        profile.onboarding_completed = True
        profile.save()
        return redirect('dashboard')
    return render(request, 'core/onboarding.html', {'form': form})


@login_required
def dashboard(request):
    """Dashboard with the profile summary. Sends users who haven't onboarded back to the questionnaire."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    return render(request, 'core/dashboard.html', {'profile': profile})


@login_required
def user_profile_view(request):
    # Only ever the signed-in user's own profile: plans and history are private.
    user_profile = UserProfile.objects.filter(user=request.user)

    context = {
        "users": user_profile
    }
    return render(request, "core/display_user_info.html", context)