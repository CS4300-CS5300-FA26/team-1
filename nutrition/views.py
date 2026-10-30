from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import UserProfile

from .planner import DAY_NAMES
from .services import meal_details, meals_for_pattern, weekly_meal_plan


def _plan_for(request):
    """The user's profile and this week's plan, or a redirect if they haven't onboarded yet."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return profile, None, redirect('onboarding')
    result = weekly_meal_plan(request.user, profile.weekly_food_budget, meals_for_pattern(profile.meal_pattern))
    return profile, result, None


def _selected(plan, day_name: str | None, meal_name: str | None):
    """The planned day and meal named in the query string, or None for either that isn't in the plan."""
    day = plan.day(day_name) if day_name else None
    meal = day.meal(meal_name) if day and meal_name else None
    return day, meal


@login_required
def meal_plan(request):
    """This week's budget meal plan (story D-5): a day picker, the day's meals, and the selected meal's details.

    Works without JavaScript: the day and meal links reload the page with ?day=&meal=.
    meal_plan.js switches days and loads details in place instead.
    """
    _, result, redirect_response = _plan_for(request)
    if redirect_response:
        return redirect_response
    context = {'result': result, 'plan': result.plan}
    if result.plan:
        day, meal = _selected(result.plan, request.GET.get('day'), request.GET.get('meal'))
        day = day or result.plan.days[timezone.localdate().weekday()]  # default to today
        meal = meal or day.meals[0]
        index = result.plan.days.index(day)
        context.update(
            selected_day=day,
            selected_meal=meal,
            previous_day=result.plan.days[index - 1],
            next_day=result.plan.days[(index + 1) % len(DAY_NAMES)],
            details=meal_details(meal.recipe),
        )
    return render(request, 'nutrition/meal_plan.html', context)


@login_required
def meal_details_fragment(request):
    """Just the details panel for one meal of the user's own plan (fetched by meal_plan.js)."""
    _, result, redirect_response = _plan_for(request)
    if redirect_response:
        return redirect_response
    if not result.plan:
        raise Http404('Meal suggestions are unavailable.')
    day, meal = _selected(result.plan, request.GET.get('day'), request.GET.get('meal'))
    if not meal:
        raise Http404('That meal is not in your plan.')
    return render(
        request,
        'nutrition/_meal_details.html',
        {'selected_day': day, 'selected_meal': meal, 'details': meal_details(meal.recipe), 'result': result},
    )
