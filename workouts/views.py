from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import UserProfile

from .domain import DAY_NAMES
from .forms import PreferencesForm, SessionLogForm
from .models import PlannedWorkout, WorkoutSession
from .services import (
    current_plan,
    days_per_week,
    monday_of,
    new_plan,
    recent_sessions,
    save_session,
    session_log,
    session_totals,
    set_days_per_week,
    start_session,
    week_overview,
    weekly_summaries,
)


def _profile(request) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return profile


@login_required
def this_week(request):
    """This Week: the weekly split, one row per day, with a way to start each workout."""
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    plan = current_plan(request.user, profile)
    days = week_overview(plan)
    context: dict[str, Any] = {
        'plan': plan,
        'days': days,
        'week_end': plan.week_start + timedelta(days=6),
        'planned_count': sum(1 for day in days if day.workout),
        'done_count': sum(1 for day in days if day.status == 'done'),
        'preferences_form': PreferencesForm(initial={'days_per_week': days_per_week(request.user, profile)}),
        'equipment': profile.equipment_labels(),
        'goal_label': profile.get_goal_display().lower(),
    }
    return render(request, 'workouts/this_week.html', context)


@login_required
@require_POST
def plan_new(request):
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    new_plan(request.user, profile)
    messages.success(request, 'Here is a new workout plan for this week.')
    return redirect('workouts_this_week')


@login_required
@require_POST
def preferences(request):
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    form = PreferencesForm(request.POST)
    if form.is_valid():
        set_days_per_week(request.user, form.cleaned_data['days_per_week'])
        messages.success(request, f'Your plan now has {form.cleaned_data["days_per_week"]} training days a week.')
    else:
        messages.error(request, 'Choose 3, 4, or 5 training days a week.')
    return redirect('workouts_this_week')


@login_required
@require_POST
def start(request, workout_id: int):
    """Start (or go back to) the session for a planned workout of this week."""
    # Scoped to the signed-in user's own plans: anyone else's id is a 404.
    workout = get_object_or_404(PlannedWorkout.objects.select_related('plan'), pk=workout_id, plan__user=request.user)
    if workout.plan.week_start != monday_of(timezone.localdate()):
        messages.error(request, 'That workout belongs to a past week. Open This Week to start a current one.')
        return redirect('workouts_this_week')
    session = start_session(request.user, workout)
    return redirect('workouts_session', session_id=session.pk)


@login_required
def session(request, session_id: int):
    """Log a workout: reps and weight per set, then save or finish."""
    workout_session = get_object_or_404(
        WorkoutSession.objects.select_related('planned_workout'), pk=session_id, user=request.user
    )
    logs = session_log(workout_session)
    posted = request.method == 'POST'
    action = request.POST.get('action') if posted else None
    if posted and action not in ('save', 'finish'):
        messages.error(request, 'Choose Save progress or Finish workout.')
        return redirect('workouts_session', session_id=workout_session.pk)
    form = SessionLogForm(
        logs,
        request.POST if posted else None,
        finishing=action == 'finish',
        has_saved_sets=workout_session.sets.exists(),
    )
    if posted and form.is_valid():
        save_session(workout_session, form.entries(), finish=action == 'finish')
        if action == 'finish':
            messages.success(request, f'{workout_session.title} is done. Nice work.')
            return redirect('workouts_history')
        messages.success(request, 'Progress saved.')
        return redirect('workouts_session', session_id=workout_session.pk)
    return render(
        request,
        'workouts/session.html',
        {
            'session': workout_session,
            'form': form,
            'blocks': form.blocks(),
            'day_name': DAY_NAMES[workout_session.planned_workout.day] if workout_session.planned_workout else None,
        },
    )


@login_required
def history(request):
    """Simple progress: consistency and volume by week, and the workouts finished recently."""
    sessions = []
    for finished in recent_sessions(request.user):
        sets_done, volume = session_totals(finished)
        sessions.append({'session': finished, 'sets': sets_done, 'volume': volume})
    return render(
        request,
        'workouts/history.html',
        {'weeks': weekly_summaries(request.user), 'sessions': sessions},
    )
