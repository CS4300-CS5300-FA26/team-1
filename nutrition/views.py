from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import UserProfile

from .domain import DAY_NAMES, MEALS
from .services import current_meal_plan, new_meal_plan
from .targets import DAILY_VALUES, DAILY_VALUES_KCAL

DAY_KEYS = tuple(name.lower() for name in DAY_NAMES)


def _profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return profile


def _selected_day(request_data, today_index: int) -> int:
    """The day named in the request if it's a day of the week (never echo raw input), else today."""
    return DAY_KEYS.index(request_data['day']) if request_data.get('day') in DAY_KEYS else today_index


def macro_rows(nutrients, targets, coverage: float) -> list[dict[str, Any]]:
    """Each macro's planned grams against the day's target scaled to the meals planned, for the macro tiles."""
    rows = []
    for label, actual, target in (
        ('Protein', nutrients.protein_g, targets.protein_g),
        ('Carbs', nutrients.carbs_g, targets.carbs_g),
        ('Fat', nutrients.fat_g, targets.fat_g),
    ):
        scaled = target * coverage
        rows.append(
            {
                'label': label,
                'grams': round(actual),
                'target': round(scaled),
                'percent': min(round(actual / scaled * 100), 100),
            }
        )
    return rows


@login_required
def meal_plan(request):
    """This week's meal plan (story D-5): a week strip, and the chosen day's meals with their recipes and totals.

    Every day is in the page; without JavaScript the day links reload with ?day=, and meal_plan.js switches days in
    place instead. Recipes open inline (<details>), so choosing a meal never moves the page.
    """
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    result = current_meal_plan(request.user, profile.meal_keys(), profile.weekly_food_budget)
    context: dict[str, Any] = {'result': result, 'workouts_link': settings.NUTRITION_WORKOUTS_LINK}
    if result.plan is not None:
        plan = result.plan
        today = timezone.localdate()
        this_week = result.week_start <= today <= result.week_end
        today_index = (today - result.week_start).days if this_week else 0
        day = _selected_day(request.GET, today_index)
        coverage = len(plan.meal_keys) / len(MEALS)
        context.update(
            days=[
                {
                    'index': index,
                    'key': DAY_KEYS[index],
                    'name': name,
                    'date': result.week_start + timedelta(days=index),
                    'is_today': this_week and index == today_index,
                    'is_selected': index == day,
                    'meals': plan.day_meals(index),
                    'nutrients': plan.day_nutrients(index),
                    'macros': macro_rows(plan.day_nutrients(index), plan.daily_targets[index], coverage),
                }
                for index, name in enumerate(DAY_NAMES)
            ],
            selected_day_key=DAY_KEYS[day],
            selected_day_name=DAY_NAMES[day],
            previous_day_key=DAY_KEYS[(day - 1) % len(DAY_KEYS)],
            next_day_key=DAY_KEYS[(day + 1) % len(DAY_KEYS)],
            partial_day=len(plan.meal_keys) < len(MEALS),
            daily_values=DAILY_VALUES,
            daily_values_kcal=DAILY_VALUES_KCAL,
        )
    return render(request, 'nutrition/meal_plan.html', context)


@login_required
@require_POST
def meal_plan_new(request):
    """Replace this week's plan with a different one."""
    profile = _profile(request)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    result = new_meal_plan(request.user, profile.meal_keys(), profile.weekly_food_budget)
    if result.unavailable:
        messages.error(request, "We couldn't make a new meal plan right now. Please try again later.")
    else:
        messages.success(request, 'Here is a new meal plan for this week.')
    query = {}
    if request.POST.get('day') in DAY_KEYS:
        query['day'] = request.POST['day']
    url = reverse('meal_plan')
    return redirect(f'{url}?{urlencode(query)}' if query else url)
