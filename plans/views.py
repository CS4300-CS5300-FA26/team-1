from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import UserProfile
from spotify import config as spotify_config
from spotify import services as spotify_services

from .forms import SplitChoiceForm
from .generator import SPLIT_LABELS, available_splits, split_of
from .services import MAX_SPLIT_SWITCHES, SwitchResult, get_weekly_plan, switch_split

# The music result of the workout started today, kept between the POST that starts it and the workout screen.
WORKOUT_MUSIC_SESSION_KEY = 'workout_music'


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
            'ai_built': not is_starter and plan.get('source') == 'ai',
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


def _todays_workout(plan, today):
    return plan['days'][today.weekday()]


@login_required
@require_POST
def start_workout(request):
    """Start today's workout, and a playlist for it when Spotify is linked. The workout starts whatever Spotify says."""
    today = timezone.localdate()
    loaded = _load_plan(request, today)
    if loaded is None:
        return redirect('onboarding')
    day = _todays_workout(loaded[0], today)
    if not day['exercises']:
        messages.info(request, 'Today is a rest day, so there is no workout to start.')
        return redirect('this_week')
    if spotify_config.is_configured():
        music = spotify_services.start_workout_music(request.user, day['name'])
    else:
        music = spotify_services.WorkoutMusic(spotify_services.MUSIC_NOT_LINKED)
    request.session[WORKOUT_MUSIC_SESSION_KEY] = {**music.as_dict(), 'date': today.isoformat()}
    # Redirect so reloading the workout screen doesn't start the music again.
    return redirect('workout')


@login_required
def workout(request):
    """Today's workout screen: the exercises, and what happened to the music if the workout was started."""
    today = timezone.localdate()
    loaded = _load_plan(request, today)
    if loaded is None:
        return redirect('onboarding')
    music = request.session.get(WORKOUT_MUSIC_SESSION_KEY)
    if not isinstance(music, dict) or music.get('date') != today.isoformat():
        music = None
    return render(
        request,
        'plans/workout.html',
        {
            'day': _todays_workout(loaded[0], today),
            'music': music,
            'spotify_configured': spotify_config.is_configured(),
        },
    )
