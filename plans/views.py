from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import UserProfile

from .services import get_weekly_plan


def _load_plan(request, today):
    """Return (plan, is_starter), or None if the user still needs to finish onboarding."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return None
    return get_weekly_plan(profile, today)


@login_required
def this_week(request):
    """Seven days of workouts (exercises, sets, reps) plus today's macro targets."""
    today = timezone.localdate()
    loaded = _load_plan(request, today)
    if loaded is None:
        return redirect('onboarding')
    plan, is_starter = loaded
    days = [{**day, 'is_today': index == today.weekday()} for index, day in enumerate(plan['days'])]
    return render(request, 'plans/this_week.html', {
        'days': days,
        'macros': plan['macros'],
        'is_starter': is_starter,
    })


@login_required
def nutrition(request):
    """Daily macro targets that match this week's plan."""
    loaded = _load_plan(request, timezone.localdate())
    if loaded is None:
        return redirect('onboarding')
    plan, is_starter = loaded
    return render(request, 'plans/nutrition.html', {
        'macros': plan['macros'],
        'is_starter': is_starter,
    })
