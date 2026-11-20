"""Tests for the Meal Plan page (story D-5) and its "generate a new plan" action."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile

from .models import WeeklyMealPlan
from .planner import build_week_plan
from .services import MealPlanResult, week_start
from .templatetags.meal_plan import servings
from .views import DAY_KEYS

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'
FLAT_PRICES = 'nutrition.testing.FlatGroceryPrices'
# The "no personal targets yet" fallback, pinned so these tests keep covering it now that D-4 is connected.
NO_TARGETS = 'nutrition.connectors.NoMacroTargets'


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

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=NO_TARGETS)
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

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=NO_TARGETS)
    def test_daily_values_notice_until_d4(self):
        text = page_text(self.client.get(reverse('meal_plan')))
        self.assertIn("Your personal macro targets aren't ready yet", text)
        self.assertIn('2,000-calorie FDA Daily Values: 50 g protein, 275 g carbohydrate, and 78 g fat', text)

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE='nutrition.connectors.NoGroceryPrices')
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
        self.assertContains(
            response, f'<a class="btn btn--primary" href="{reverse("this_week")}">Open This Week</a>', html=True
        )
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


@override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'meal_plan': (2, 60 * 60)})
class NewPlanThrottleTests(TestCase):
    """Security assessment F-1: one account could hold every Gunicorn worker by asking for new plans in parallel."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def use_up_the_limit(self):
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 302)

    def test_new_plans_are_limited_per_user(self):
        self.use_up_the_limit()
        before = WeeklyMealPlan.objects.values_list('seed', 'created_at').get(user=self.user)
        response = self.client.post(reverse('meal_plan_new'), {'day': 'friday'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        self.assertContains(
            response,
            'You&#x27;ve asked for a lot of new meal plans. Please wait a while and try again.',
            status_code=429,
        )
        self.assertEqual(WeeklyMealPlan.objects.values_list('seed', 'created_at').get(user=self.user), before)

    def test_a_blocked_request_does_not_run_the_planner(self):
        self.use_up_the_limit()
        with mock.patch('nutrition.views.new_meal_plan') as planner:
            self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 429)
        planner.assert_not_called()

    def test_a_blocked_request_keeps_the_day_the_user_was_looking_at(self):
        # Review of PR #61: the refused page read the day from the query string, but the form posts it.
        self.use_up_the_limit()
        other_day = DAY_KEYS[(timezone.localdate().weekday() + 3) % 7]
        response = self.client.post(reverse('meal_plan_new'), {'day': other_day})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.context['selected_day_key'], other_day)
        self.assertContains(response, f'data-day-link="{other_day}"', status_code=429)

    def test_a_blocked_request_shows_the_saved_plan_without_planning(self):
        self.use_up_the_limit()
        with mock.patch('nutrition.services.build_week_plan') as planner:
            response = self.client.post(reverse('meal_plan_new'))
        planner.assert_not_called()
        self.assertEqual(response.status_code, 429)
        self.assertIsNotNone(response.context['result'].plan)

    def test_a_blocked_request_does_not_plan_when_the_settings_changed(self):
        # The page used to be rendered by current_meal_plan, which makes a plan when the saved one is stale.
        self.use_up_the_limit()
        UserProfile.objects.filter(user=self.user).update(planned_meals=['dinner'])
        before = WeeklyMealPlan.objects.values_list('seed', 'inputs').get(user=self.user)
        with mock.patch('nutrition.services.build_week_plan') as planner:
            response = self.client.post(reverse('meal_plan_new'))
        planner.assert_not_called()
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.context['result'].not_saved)
        self.assertIn("There's no saved meal plan for your current meal settings yet.", page_text(response))
        self.assertNotIn('temporarily unavailable', page_text(response))
        self.assertEqual(WeeklyMealPlan.objects.values_list('seed', 'inputs').get(user=self.user), before)

    def test_a_blocked_request_does_not_plan_when_there_is_no_saved_plan(self):
        self.use_up_the_limit()
        WeeklyMealPlan.objects.filter(user=self.user).delete()
        with mock.patch('nutrition.services.build_week_plan') as planner:
            response = self.client.post(reverse('meal_plan_new'))
        planner.assert_not_called()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, f'href="{reverse("meal_plan")}"', status_code=429)
        self.assertFalse(WeeklyMealPlan.objects.filter(user=self.user).exists())

    def test_the_limit_is_per_user(self):
        self.use_up_the_limit()
        self.client.force_login(make_user('alex'))
        self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 302)

    def test_viewing_the_plan_is_not_limited(self):
        self.use_up_the_limit()
        self.assertEqual(self.client.get(reverse('meal_plan')).status_code, 200)

    def test_viewing_the_page_does_not_make_a_plan_once_the_limit_is_used_up(self):
        # The page makes a plan when the saved one is stale; that used to bypass both limits (ADR-016).
        self.use_up_the_limit()
        UserProfile.objects.filter(user=self.user).update(planned_meals=['dinner'])
        with mock.patch('nutrition.services.build_week_plan') as planner:
            response = self.client.get(reverse('meal_plan'))
        planner.assert_not_called()
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        self.assertTrue(response.context['result'].not_saved)
        self.assertIn('asked for a lot of new meal plans', page_text(response))

    def test_switching_meal_settings_back_and_forth_cannot_make_unlimited_plans(self):
        with mock.patch('nutrition.services.build_week_plan', wraps=build_week_plan) as planner:
            for meals in (['dinner'], ['lunch'], ['breakfast']):
                UserProfile.objects.filter(user=self.user).update(planned_meals=meals)
                response = self.client.get(reverse('meal_plan'))
        self.assertEqual(planner.call_count, 2)
        self.assertEqual(response.status_code, 429)


MEAL_PLAN_SLOTS = {'per_user': 1, 'total': 2, 'lease_seconds': 120, 'retry_after': 15}
BUSY = 'A new meal plan is already being made. Please wait a moment and try again.'


def signed_in_client(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


@override_settings(
    MEAL_PLAN_CONCURRENCY=MEAL_PLAN_SLOTS, AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'meal_plan': (2, 60 * 60)}
)
class NewPlanConcurrencyTests(TestCase):
    """Review of PR #61: the hourly count let a burst of parallel requests all start the planner and hold every worker.

    Each test sends a request while another is inside the planner, by sending it from the (mocked) planner itself.
    NewPlanParallelTests below does the same with real parallel requests on PostgreSQL.
    """

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def planner_that_sends(self, *clients):
        """A stand-in for new_meal_plan that, while "planning", has each client ask for a new plan."""
        statuses = []

        def plan(user, meals, budget):
            for client in clients:
                statuses.append(client.post(reverse('meal_plan_new')))
            return MealPlanResult(week_start=week_start(), plan=None)

        return plan, statuses

    def test_a_second_request_from_the_same_user_is_refused_while_the_first_is_planning(self):
        plan, responses = self.planner_that_sends(signed_in_client(self.user))
        with mock.patch('nutrition.views.new_meal_plan', side_effect=plan) as planner:
            self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 302)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(responses[0].status_code, 429)
        self.assertEqual(responses[0]['Retry-After'], '15')
        self.assertContains(responses[0], BUSY, status_code=429)

    def test_planner_runs_in_progress_are_capped_for_everyone(self):
        second, third = signed_in_client(make_user('alex')), signed_in_client(make_user('kim'))
        plan, responses = self.planner_that_sends(third)  # kim asks while sam and alex are both planning
        outer, _ = self.planner_that_sends(second)

        def first_run(user, meals, budget):
            with mock.patch('nutrition.views.new_meal_plan', side_effect=plan):
                return outer(user, meals, budget)

        with mock.patch('nutrition.views.new_meal_plan', side_effect=first_run):
            self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 302)
        self.assertContains(responses[0], BUSY, status_code=429)
        # Once both runs finish, the slots are free again.
        self.assertEqual(third.post(reverse('meal_plan_new')).status_code, 302)

    def test_a_refused_request_is_not_counted_against_the_hourly_limit(self):
        same_user = signed_in_client(self.user)
        plan, responses = self.planner_that_sends(same_user, same_user, same_user)
        with mock.patch('nutrition.views.new_meal_plan', side_effect=plan):
            self.client.post(reverse('meal_plan_new'))
        self.assertEqual([r.status_code for r in responses], [429, 429, 429])
        # One run counted so far, so one more fits in the hour (limit 2) before the hourly message.
        self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 302)
        self.assertContains(self.client.post(reverse('meal_plan_new')), 'asked for a lot of new', status_code=429)

    def test_the_slot_is_given_back_when_the_planner_fails(self):
        crash = RuntimeError('planner crashed')
        with mock.patch('nutrition.views.new_meal_plan', side_effect=crash), self.assertRaises(RuntimeError):
            self.client.post(reverse('meal_plan_new'))
        self.assertEqual(self.client.post(reverse('meal_plan_new')).status_code, 302)

    def test_viewing_the_page_does_not_make_a_second_plan_while_one_is_being_made(self):
        same_user = signed_in_client(self.user)
        views = []

        def plan(user, meals, budget):
            views.append(same_user.get(reverse('meal_plan')))  # no saved plan yet, so the page would make one
            return MealPlanResult(week_start=week_start(), plan=None)

        with (
            mock.patch('nutrition.views.new_meal_plan', side_effect=plan),
            mock.patch('nutrition.services.build_week_plan') as underlying,
        ):
            self.client.post(reverse('meal_plan_new'))
        underlying.assert_not_called()
        self.assertContains(views[0], BUSY, status_code=429)
        self.assertTrue(views[0].context['result'].not_saved)

    def test_a_busy_refusal_does_not_run_the_planner_for_the_page(self):
        plan, responses = self.planner_that_sends(signed_in_client(self.user))
        with (
            mock.patch('nutrition.views.new_meal_plan', side_effect=plan),
            mock.patch('nutrition.services.build_week_plan') as underlying,
        ):
            self.client.post(reverse('meal_plan_new'))
        underlying.assert_not_called()
        self.assertTrue(responses[0].context['result'].not_saved)


@skipUnless(connection.vendor == 'postgresql', 'parallel connections need PostgreSQL; SQLite serializes writes itself')
@override_settings(MEAL_PLAN_CONCURRENCY=MEAL_PLAN_SLOTS)
class NewPlanParallelTests(TransactionTestCase):
    """Review of PR #61 (P1): real parallel requests, through both ways of starting the planner."""

    def burst(self, send, patched):
        """Send 12 requests at once, as 3 users with 4 each; `patched` (the planner entry point) blocks until all
        the refused ones have been answered. Returns the status codes and the users whose runs started."""
        users = [make_user(name) for name in ('sam', 'alex', 'kim')]
        clients = [signed_in_client(user) for user in users for _ in range(4)]
        barrier, finish, lock = threading.Barrier(len(clients)), threading.Event(), threading.Lock()
        planning: list[int] = []

        def plan(user, meals, budget):
            with lock:
                planning.append(user.pk)
            finish.wait(10)  # stay "in the planner" until every other request has been answered
            return MealPlanResult(week_start=week_start(), plan=None)

        def ask(client):
            try:
                barrier.wait()
                return send(client).status_code
            finally:
                connection.close()

        with mock.patch(patched, side_effect=plan), ThreadPoolExecutor(len(clients)) as pool:
            futures = [pool.submit(ask, client) for client in clients]
            deadline = time.monotonic() + 10
            while sum(f.done() for f in futures) < len(clients) - MEAL_PLAN_SLOTS['total'] and (
                time.monotonic() < deadline
            ):
                time.sleep(0.01)
            finish.set()
            statuses = [f.result(10) for f in futures]
        self.assertEqual(statuses.count(429), len(clients) - MEAL_PLAN_SLOTS['total'])
        self.assertEqual(len(planning), MEAL_PLAN_SLOTS['total'])
        self.assertEqual(len(set(planning)), len(planning))  # never two runs for one user
        return statuses

    def test_a_burst_of_new_plan_requests_never_runs_more_planners_than_the_slots(self):
        statuses = self.burst(lambda client: client.post(reverse('meal_plan_new')), 'nutrition.views.new_meal_plan')
        self.assertEqual(statuses.count(302), MEAL_PLAN_SLOTS['total'])

    def test_a_burst_of_first_page_views_never_runs_more_planners_than_the_slots(self):
        # None of the users has a saved plan, so each view would make one.
        statuses = self.burst(lambda client: client.get(reverse('meal_plan')), 'nutrition.views.current_meal_plan')
        self.assertEqual(statuses.count(200), MEAL_PLAN_SLOTS['total'])


class TemplateFilterTests(TestCase):
    def test_servings_reads_naturally(self):
        self.assertEqual(servings(Decimal('1')), '1 serving')
        self.assertEqual(servings(Decimal('1.5')), '1½ servings')
        self.assertEqual(servings(Decimal('2')), '2 servings')
        self.assertEqual(servings(Decimal('0.5')), '½ servings')
        self.assertEqual(servings(Decimal('1.25')), '1.25 servings')
