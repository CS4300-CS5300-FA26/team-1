from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core.models import UserProfile
from nutrition.services import week_start

from .services import grocery_list_for


@login_required
def grocery_list(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return redirect('onboarding')
    monday = week_start()
    groceries = grocery_list_for(request.user, monday)
    budget = profile.weekly_food_budget
    over_budget_by = None
    if groceries is not None and groceries.total is not None and budget is not None and groceries.total > budget:
        over_budget_by = groceries.total - budget
    context = {
        'groceries': groceries,
        'week_start': monday,
        'week_end': monday + timedelta(days=6),
        'budget': budget,
        'over_budget_by': over_budget_by,
    }
    return render(request, 'grocery/grocery_list.html', context)