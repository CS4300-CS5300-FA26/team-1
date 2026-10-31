"""Tests for the Meal Plan page (story D-5) and its "generate a new plan" action."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile

from .models import WeeklyMealPlan
from .templatetags.meal_plan import servings

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'
FLAT_PRICES = 'nutrition.testing.FlatGroceryPrices'


def page_text(response) -> str:
    """The response body with runs of whitespace collapsed, so sentences that wrap in the template match."""
    return ' '.join(response.content.decode().split())


def make_user(name='sam', budget='50.00', onboarded=True, meals=('breakfast', 'lunch', 'dinner')):
    user = User.objects.create_user(name, f'{name}@example.com', PASSWORD)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=onboarded,
        weekly_food_budget=Decimal(budget) if budget is not None else None,
        planned_meals=list(meals),
    )
    return user


class AccessTests(TestCase):
    def test_login_is_required(self):
        for name, method in (('meal_plan', 'get'), ('meal_plan_new', 'post')):
            with self.subTest(name):
                response = getattr(self.client, method)(reverse(name))
                self.assertRedirects(
                    response, f'{reverse("login")}?next={reverse(name)}', fetch_redirect_response=False
                )

    def test_users_who_have_not_onboarded_are_sent_to_onboarding(self):
        self.client.force_login(make_user(onboarded=False))
        self.assertRedirects(
            self.client.get(reverse('meal_plan')), reverse('onboarding'), fetch_redirect_response=False
        )
        self.assertRedirects(
            self.client.post(reverse('meal_plan_new')), reverse('onboarding'), fetch_redirect_response=False
        )

    def test_a_new_plan_needs_post(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse('meal_plan_new')).status_code, 405)

    def test_the_page_uses_only_the_signed_in_users_meals(self):
        make_user('three', meals=('breakfast', 'lunch', 'dinner'))
        self.client.force_login(make_user('diner', meals=('dinner',)))
        result = self.client.get(reverse('meal_plan')).context['result']
        self.assertEqual(result.plan.meal_keys, ('dinner',))
        self.assertEqual(WeeklyMealPlan.objects.filter(user__username='three').count(), 0)


class DayViewTests(TestCase):
    """A week strip picks a day; the day's meals show as cards with their recipes opening in place."""

    def setUp(self):
        self.client.force_login(make_user())

    def test_every_day_is_in_the_page_and_only_the_chosen_one_shows(self):
        response = self.client.get(reverse('meal_plan'), {'day': 'wednesday'})
        self.assertContains(response, 'data-day-link=', count=7)
        self.assertContains(response, 'data-day-panel=', count=7)
        self.assertContains(response, 'class="meal-card"', count=21)
        content = response.content.decode()
        for day in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'):
            panel = content[content.index(f'data-day-panel="{day}"') :].split('>', 1)[0]
            with self.subTest(day=day):
                self.assertEqual('hidden' in panel, day != 'wednesday')
        self.assertContains(response, 'href="?day=wednesday" data-day-link="wednesday" data-day-name="Wednesday"')
        self.assertEqual(content.count('aria-current="true"'), 1)
        self.assertContains(response, 'href="?day=tuesday" data-day-step="-1"')
        self.assertContains(response, 'href="?day=thursday" data-day-step="1"')
        self.assertContains(
            response, '<p class="day-picker__current" aria-live="polite" data-day-current>Wednesday</p>', html=False
        )

    def test_recipes_open_in_place_without_links_that_jump(self):
        response = self.client.get(reverse('meal_plan'))
        plan = response.context['result'].plan
        self.assertContains(response, '<details class="disclosure meal-card__recipe">', count=21, html=False)
        self.assertNotContains(response, '#meal-details')
        meal = plan.meal(0, 'dinner')
        for step in meal.recipe.steps:
            self.assertContains(response, step)
        self.assertContains(response, meal.recipe.title)

    def test_each_day_shows_its_totals_against_targets(self):
        response = self.client.get(reverse('meal_plan'))
        text = page_text(response)
        self.assertIn("Monday's totals", text)
        self.assertIn('of 50 g', text)  # the Daily Values protein target, for three meals a day
        self.assertContains(response, 'class="macro-list__row"', count=21)

    def test_unknown_days_fall_back_to_today_and_are_never_echoed(self):
        response = self.client.get(reverse('meal_plan'), {'day': '<b>injected</b>'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'injected')
        self.assertEqual(sum(day['is_selected'] for day in response.context['days']), 1)

    def test_the_new_plan_form_remembers_the_day(self):
        response = self.client.get(reverse('meal_plan'), {'day': 'friday'})
        self.assertContains(response, '<input type="hidden" name="day" value="friday" data-day-input>', html=False)

    def test_daily_values_notice_until_d4(self):
        text = page_text(self.client.get(reverse('meal_plan')))
        self.assertIn("Your personal macro targets aren't ready yet", text)
        self.assertIn('2,000-calorie FDA Daily Values: 50 g protein, 275 g carbohydrate, and 78 g fat', text)

    def test_no_prices_notice_until_d6(self):
        response = self.client.get(reverse('meal_plan'))
        self.assertContains(response, "Grocery prices aren't available yet")
        self.assertNotContains(response, 'Est. $')

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER='nutrition.testing.FixedMacroTargets')
    def test_no_daily_values_notice_with_personal_targets(self):
        self.assertNotContains(self.client.get(reverse('meal_plan')), "macro targets aren't ready")


@override_settings(NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
class CostTests(TestCase):
    def test_estimated_cost_against_the_budget(self):
        self.client.force_login(make_user(budget='500.00'))
        response = self.client.get(reverse('meal_plan'))
        cost = response.context['result'].cost
        self.assertContains(response, f'Est. ${cost}')
        self.assertContains(response, 'grocery cost for the week, of your $500.00 budget')
        self.assertContains(response, 'buys whole packages')
        self.assertNotContains(response, 'over your')

    def test_a_budget_too_low_shows_the_lowest_cost_plan_and_how_far_over(self):
        self.client.force_login(make_user(budget='10.00'))
        response = self.client.get(reverse('meal_plan'))
        over = response.context['result'].over_budget_by
        self.assertContains(response, f'${over} over your $10.00 budget.')
        self.assertContains(response, 'this is the lowest-cost plan available')

    def test_no_budget_plans_for_nutrition(self):
        self.client.force_login(make_user(budget=None))
        response = self.client.get(reverse('meal_plan'))
        self.assertContains(response, "You haven't set a weekly food budget")
        self.assertContains(response, 'grocery cost for the week</span>', html=False)


@override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
class UnavailableTests(TestCase):
    def test_the_page_says_so_and_links_to_workouts(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse('meal_plan'))
        self.assertContains(response, 'Meal suggestions are temporarily unavailable.')
        self.assertContains(response, f'href="{reverse("dashboard")}"')
        self.assertNotContains(response, 'week-calendar')

    @override_settings(NUTRITION_WORKOUTS_LINK={'url_name': 'user_profile', 'text': 'Open This Week'})
    def test_the_workouts_link_is_a_connector_for_d3(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse('meal_plan'))
        self.assertContains(
            response, f'<a class="btn btn--primary" href="{reverse("user_profile")}">Open This Week</a>', html=True
        )

    def test_a_new_plan_reports_the_failure(self):
        self.client.force_login(make_user())
        response = self.client.post(reverse('meal_plan_new'), follow=True)
        self.assertContains(response, 'We couldn&#x27;t make a new meal plan right now.')


class NewPlanTests(TestCase):
    def test_a_new_plan_replaces_the_week_and_keeps_the_day(self):
        self.client.force_login(make_user())
        first = self.client.get(reverse('meal_plan')).context['result'].plan
        response = self.client.post(reverse('meal_plan_new'), {'day': 'friday'})
        self.assertRedirects(response, f'{reverse("meal_plan")}?day=friday', fetch_redirect_response=False)
        page = self.client.get(response['Location'])
        self.assertContains(page, 'Here is a new meal plan for this week.')
        self.assertNotEqual(page.context['result'].plan, first)

    def test_an_unknown_day_is_dropped_from_the_redirect(self):
        self.client.force_login(make_user())
        response = self.client.post(reverse('meal_plan_new'), {'day': 'https://evil.example'})
        self.assertRedirects(response, reverse('meal_plan'), fetch_redirect_response=False)


class TemplateFilterTests(TestCase):
    def test_servings_reads_naturally(self):
        self.assertEqual(servings(Decimal('1')), '1 serving')
        self.assertEqual(servings(Decimal('1.5')), '1½ servings')
        self.assertEqual(servings(Decimal('2')), '2 servings')
        self.assertEqual(servings(Decimal('0.5')), '½ servings')
        self.assertEqual(servings(Decimal('1.25')), '1.25 servings')
