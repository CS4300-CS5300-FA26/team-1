from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import UserProfile

from .domain import DAY_NAMES
from .forms import SessionLogForm
from .models import WorkoutSession
from .services import (
    NotATrainingDay,
    current_weekly_plan,
    recent_sessions,
    save_session,
    session_log,
    session_totals,
    start_session,
    weekly_summaries,
)


@login_required
@require_POST
def start(request, day: int):
    """Start (or go back to) the workout for one training day of this week's plan (plans app, ADR-012)."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    # Only ever the signed-in user's own plan for the current week.
    plan = current_weekly_plan(request.user)
    if plan is None:
        messages.error(request, 'Open This Week to get your plan for the week, then start a workout from it.')
        return redirect('this_week')
    try:
        session = start_session(request.user, plan, day)
    except NotATrainingDay:
        messages.error(request, 'That day has no workout in your plan for this week.')
        return redirect('this_week')
    return redirect('workouts_session', session_id=session.pk)


@login_required
def session(request, session_id: int):
    """Log a workout: reps and weight per set (seconds for holds, minutes for cardio), then save or finish."""
    workout_session = get_object_or_404(WorkoutSession, pk=session_id, user=request.user)
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
        save_session(workout_session, form.entries(), form.names(), finish=action == 'finish')
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
            'day_name': DAY_NAMES[workout_session.day],
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
