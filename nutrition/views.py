from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core.models import UserProfile

from .services import weekly_meal_plan


@login_required
def meal_plan(request):
    """This week's budget meal plan (story D-5). Needs the budget from onboarding."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed or profile.weekly_food_budget is None:
        return redirect('onboarding')
    result = weekly_meal_plan(request.user, profile.weekly_food_budget)
    return render(request, 'nutrition/meal_plan.html', {'result': result, 'plan': result.plan})
