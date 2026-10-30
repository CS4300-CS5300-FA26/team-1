from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import UserProfile

from .domain import MEALS
from .planner import DAY_NAMES
from .report import build_report, ingredients_csv
from .services import (
    current_meal_plan,
    discard_draft,
    generate_new_meal_plan,
    meal_details,
    meals_for_pattern,
    save_meal_plan,
)

DAY_KEYS = tuple(name.lower() for name in DAY_NAMES)


def _profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return profile


def _plan_args(request, profile):
    """What every meal plan use case needs about this user."""
    return request.user, request.session, profile.weekly_food_budget, meals_for_pattern(profile.meal_pattern)


def _selected(plan, day_name: str | None, meal_name: str | None):
    """The planned day and meal named in the query string, or None for either that isn't in the plan."""
    day = plan.day(day_name) if day_name else None
    meal = day.meal(meal_name) if day and meal_name else None
    return day, meal


def _back_to_plan(request):
    """Redirect to the meal plan, keeping the chosen day and meal if they're valid (never echo raw input)."""
    query = {}
    if request.POST.get('day') in DAY_KEYS:
        query['day'] = request.POST['day']
        if request.POST.get('meal') in MEALS:
            query['meal'] = request.POST['meal']
    url = reverse('meal_plan')
    return redirect(f'{url}?{urlencode(query)}' if query else url)


@login_required
def meal_plan(request):
    """This week's budget meal plan (story D-5): a day picker, the day's meals, and the selected meal's details.

    Works without JavaScript: the day and meal links reload the page with ?day=&meal=.
    meal_plan.js switches days, loads details in place, and runs the details tabs instead.
    """
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    current = current_meal_plan(*_plan_args(request, profile))
    context: dict[str, Any] = {'current': current, 'plan': current.plan}
    if current.plan:
        day, meal = _selected(current.plan, request.GET.get('day'), request.GET.get('meal'))
        day = day or current.plan.days[timezone.localdate().weekday()]  # default to today
        meal = meal or day.meals[0]
        index = current.plan.days.index(day)
        context.update(
            selected_day=day,
            selected_meal=meal,
            previous_day=current.plan.days[index - 1],
            next_day=current.plan.days[(index + 1) % len(DAY_NAMES)],
            details=meal_details(meal.recipe),
        )
    return render(request, 'nutrition/meal_plan.html', context)


@login_required
def meal_details_fragment(request):
    """Just the details panel for one meal of the user's own plan (fetched by meal_plan.js)."""
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    current = current_meal_plan(*_plan_args(request, profile))
    if not current.plan:
        raise Http404('Meal suggestions are unavailable.')
    day, meal = _selected(current.plan, request.GET.get('day'), request.GET.get('meal'))
    if not meal:
        raise Http404('That meal is not in your plan.')
    return render(
        request,
        'nutrition/_meal_details.html',
        {'selected_day': day, 'selected_meal': meal, 'details': meal_details(meal.recipe)},
    )


@login_required
@require_POST
def save_plan(request):
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    current = save_meal_plan(*_plan_args(request, profile))
    if current:
        messages.success(request, f'Meal plan saved for the week of {current.week_start:%B} {current.week_start.day}.')
    else:
        messages.error(request, "There's no meal plan to save right now. Please try again later.")
    return _back_to_plan(request)


@login_required
@require_POST
def new_plan(request):
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    if generate_new_meal_plan(*_plan_args(request, profile)):
        messages.info(request, 'Here is a new meal plan. Save it to keep it for the week.')
    else:
        messages.error(request, "We couldn't make a new meal plan right now. Please try again later.")
    return redirect('meal_plan')


@login_required
@require_POST
def discard_plan(request):
    discard_draft(request.session)
    messages.info(request, 'Showing your saved meal plan.')
    return redirect('meal_plan')


@login_required
def meal_plan_report(request):
    """Overview of this week's plan: budget use, daily spend, and ingredients (with a CSV download)."""
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    current = current_meal_plan(*_plan_args(request, profile))
    report = build_report(current.plan, lambda meal: meal_details(meal.recipe)) if current.plan else None
    return render(request, 'nutrition/report.html', {'current': current, 'report': report})


@login_required
def ingredients_download(request):
    """This week's ingredients as a CSV file. Only ever the signed-in user's own plan."""
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    current = current_meal_plan(*_plan_args(request, profile))
    if not current.plan:
        raise Http404('Meal suggestions are unavailable.')
    report = build_report(current.plan, lambda meal: meal_details(meal.recipe))
    # The BOM lets Excel detect UTF-8. The filename is built from a date only, never from user input.
    response = HttpResponse('﻿' + ingredients_csv(report), content_type='text/csv; charset=utf-8')
    filename = f'fitpro-ingredients-week-of-{current.week_start.isoformat()}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response
