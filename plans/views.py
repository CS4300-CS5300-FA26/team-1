from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import UserProfile

from .forms import SplitChoiceForm
from .generator import SPLIT_LABELS, available_splits, split_of
from .services import MAX_SPLIT_SWITCHES, SwitchResult, get_weekly_plan, switch_split


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
    trained = sum(1 for day in days if day['exercises'])
    split_key = None if is_starter else split_of(plan)
    return render(
        request,
        'plans/this_week.html',
        {
            'days': days,
            'macros': plan['macros'],
            'is_starter': is_starter,
            'split_key': split_key,
            'split_label': SPLIT_LABELS.get(split_key or ''),
            'split_choices': [(key, SPLIT_LABELS[key]) for key in available_splits(trained)],
            'switches_left': max(0, MAX_SPLIT_SWITCHES - plan.get('switches', 0)),
        },
    )


SWITCH_MESSAGES = {
    SwitchResult.CHANGED: (messages.SUCCESS, 'Your workout split is updated. Your macro targets stay the same.'),
    SwitchResult.UNCHANGED: (messages.INFO, 'You are already on that split.'),
    SwitchResult.LIMIT: (
        messages.ERROR,
        f'You have reached the limit of {MAX_SPLIT_SWITCHES} split switches for this week.',
    ),
    SwitchResult.UNAVAILABLE: (messages.ERROR, 'That split is not available right now. Please try again later.'),
}


@login_required
@require_POST
def change_split(request):
    """Switch this week's workout split to the one chosen, or to the next in rotation."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    form = SplitChoiceForm(request.POST)
    if form.is_valid():
        level, text = SWITCH_MESSAGES[switch_split(profile, form.cleaned_data['split'])]
    else:
        level, text = messages.ERROR, 'Choose one of the listed workout splits.'
    messages.add_message(request, level, text)
    return redirect('this_week')


@login_required
def nutrition(request):
    """Daily macro targets that match this week's plan."""
    loaded = _load_plan(request, timezone.localdate())
    if loaded is None:
        return redirect('onboarding')
    plan, is_starter = loaded
    return render(
        request,
        'plans/nutrition.html',
        {
            'macros': plan['macros'],
            'is_starter': is_starter,
        },
    )
