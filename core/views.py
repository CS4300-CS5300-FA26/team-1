from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import UserProfile


def home(request):
    return render(request, 'core/home.html')


@login_required
def onboarding(request):
    # Placeholder: the onboarding questionnaire is its own user story. Registration lands
    # here, so that story only has to replace this view and its template.
    return render(request, 'core/onboarding.html')


@login_required
def user_profile_view(request):
    # Only ever the signed-in user's own profile: plans and history are private.
    user_profile = UserProfile.objects.filter(user=request.user)

    context = {
        "users": user_profile
    }
    return render(request, "core/display_user_info.html", context)