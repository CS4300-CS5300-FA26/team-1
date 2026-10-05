from django.shortcuts import render
from .models import UserProfile


def home(request):
    return render(request, 'core/home.html')

def user_profile_view(request):
    user_profile = UserProfile.objects.all()
    
    context = {
        "users": user_profile
    }
    return render(request, "core/display_user_info.html", context)