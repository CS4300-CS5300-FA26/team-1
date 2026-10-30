"""Saving a week's meal plan, generating a new one, and the snapshots behind them."""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile

from . import plan_store
from .models import SavedMealPlan
from .planner import build_week_plan
from .services import DRAFT_SESSION_KEY, current_meal_plan, generate_new_meal_plan, save_meal_plan
from .testing import FIXED_RECIPES, FIXED_WEEKLY_TARGETS

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'
FIXED_SOURCE = 'nutrition.testing.FixedRecipeSource'
A_THURSDAY = date(2026, 10, 29)
ITS_MONDAY = date(2026, 10, 26)
THREE_MEALS = ('breakfast', 'lunch', 'dinner')


def recipe_ids(plan):
    return [meal.recipe.id for day in plan.days for meal in day.meals]


def make_user(username='sam', budget='50.00'):
    user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
    UserProfile.objects.create(
        user=user, onboarding_completed=True, weekly_food_budget=Decimal(budget), meal_pattern='three'
    )
    return user


class SnapshotTests(TestCase):
    def test_round_trip_keeps_the_whole_plan(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('50'), targets=FIXED_WEEKLY_TARGETS)
        loaded = plan_store.load(plan_store.dump(plan_store.Snapshot(plan, 'Test recipes.')))
        assert loaded is not None
        self.assertEqual(loaded.plan, plan)
        self.assertEqual(loaded.attribution, 'Test recipes.')

    def test_unreadable_snapshots_are_ignored(self):
        good = plan_store.dump(plan_store.Snapshot(build_week_plan(FIXED_RECIPES, Decimal('50'))))
        broken = [
            None,
            {},
            {**good, 'version': 99},
            {**good, 'budget': 'lots'},
            {**good, 'days': [{'day_name': 'Monday'}]},
            {
                **good,
                'days': [
                    {
                        'day_name': 'Monday',
                        'targets': None,
                        'meals': [{'meal': 'lunch', 'targets': None, 'recipe': {'id': 'x'}}],
                    }
                ],
            },
        ]
        for data in broken:
            with self.subTest(data=str(data)[:60]):
                self.assertIsNone(plan_store.load(data))


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class SavedPlanServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.session: dict = {}

    def current(self, budget='50', today=A_THURSDAY):
        return current_meal_plan(self.user, self.session, Decimal(budget), THREE_MEALS, today)

    def test_first_visit_generates_a_plan_and_keeps_it_as_an_unsaved_draft(self):
        current = self.current()
        self.assertFalse(current.is_saved)
        self.assertEqual(current.week_start, ITS_MONDAY)
        self.assertIn(DRAFT_SESSION_KEY, self.session)
        self.assertEqual(self.current().plan, current.plan)  # the draft is reused, not regenerated

    def test_saving_stores_the_plan_for_the_week_with_a_timestamp(self):
        shown = self.current()
        saved = save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        assert saved is not None
        row = SavedMealPlan.objects.get(user=self.user)
        self.assertEqual(row.week_start, ITS_MONDAY)
        self.assertIsNotNone(row.saved_at)
        loaded = plan_store.load(row.plan)
        assert loaded is not None
        self.assertEqual(loaded.plan, shown.plan)
        self.assertEqual(str(row), f'{self.user} week of 2026-10-26')
        self.assertTrue(saved.is_saved)
        self.assertNotIn(DRAFT_SESSION_KEY, self.session)
        self.assertTrue(self.current().is_saved)

    def test_saved_plan_stays_the_same_when_the_recipes_change(self):
        self.current()
        save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        before = self.current().plan
        with mock.patch('nutrition.testing.FixedRecipeSource.budget_recipes', return_value=list(FIXED_RECIPES[3:])):
            self.assertEqual(self.current().plan, before)

    def test_generating_a_new_plan_changes_meals_and_leaves_the_saved_plan_alone(self):
        save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        saved_plan = self.current().plan
        new = generate_new_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        assert new is not None and new.plan is not None and saved_plan is not None
        self.assertNotEqual(recipe_ids(new.plan), recipe_ids(saved_plan))
        self.assertFalse(new.is_saved)
        still_saved = plan_store.load(SavedMealPlan.objects.get().plan)
        assert still_saved is not None
        self.assertEqual(still_saved.plan, saved_plan)
        self.assertEqual(self.current().plan, new.plan)  # the new draft is what's shown now

    def test_repeated_new_plans_keep_avoiding_what_was_shown(self):
        first = self.current().plan
        second = generate_new_meal_plan(self.user, self.session, Decimal('50'), ('dinner',), A_THURSDAY)
        third = generate_new_meal_plan(self.user, self.session, Decimal('50'), ('dinner',), A_THURSDAY)
        assert first and second and third and second.plan and third.plan
        self.assertFalse(set(recipe_ids(second.plan)) & set(recipe_ids(third.plan)))

    def test_a_new_week_starts_fresh(self):
        self.current()
        save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        next_week = self.current(today=A_THURSDAY + timedelta(days=7))
        self.assertFalse(next_week.is_saved)
        self.assertIsNone(next_week.saved)
        self.assertEqual(next_week.week_start, ITS_MONDAY + timedelta(days=7))

    def test_changing_the_budget_replaces_an_unsaved_draft(self):
        self.assertEqual(self.current('50').plan.budget, Decimal('50.00'))
        self.assertEqual(self.current('20').plan.budget, Decimal('20.00'))

    def test_saved_plans_belong_to_one_user(self):
        save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        other = make_user('other')
        self.assertIsNone(current_meal_plan(other, {}, Decimal('50'), THREE_MEALS, A_THURSDAY).saved)

    def test_saving_twice_in_a_week_updates_the_same_row(self):
        save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        generate_new_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY)
        self.assertEqual(SavedMealPlan.objects.filter(user=self.user).count(), 1)

    def test_a_corrupt_saved_plan_is_replaced_by_a_fresh_one(self):
        SavedMealPlan.objects.create(user=self.user, week_start=ITS_MONDAY, plan={'version': 1, 'days': 'nope'})
        current = self.current()
        self.assertIsNotNone(current.plan)
        self.assertFalse(current.is_saved)

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_nothing_to_save_or_regenerate_when_recipes_are_unavailable(self):
        self.assertIsNone(save_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY))
        self.assertIsNone(generate_new_meal_plan(self.user, self.session, Decimal('50'), THREE_MEALS, A_THURSDAY))
        self.assertFalse(SavedMealPlan.objects.exists())


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class SavedPlanViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def page(self):
        return self.client.get(reverse('meal_plan'))

    def test_new_plan_shows_not_saved_with_save_and_generate_buttons(self):
        response = self.page()
        self.assertContains(response, 'Not saved')
        self.assertContains(response, 'Save meal plan')
        self.assertContains(response, 'Generate a new meal plan')
        self.assertNotContains(response, 'Back to saved plan')

    def test_save_keeps_the_selection_and_confirms(self):
        self.page()
        response = self.client.post(reverse('meal_plan_save'), {'day': 'friday', 'meal': 'dinner'}, follow=True)
        self.assertRedirects(response, f'{reverse("meal_plan")}?day=friday&meal=dinner')
        self.assertContains(response, 'Meal plan saved for the week of')
        self.assertContains(response, 'status-badge--saved')
        self.assertNotContains(response, '>Save meal plan<')
        self.assertTrue(SavedMealPlan.objects.filter(user=self.user).exists())

    def test_save_ignores_a_bad_selection_in_the_redirect(self):
        response = self.client.post(reverse('meal_plan_save'), {'day': '//evil.example', 'meal': '<x>'})
        self.assertRedirects(response, reverse('meal_plan'), fetch_redirect_response=False)

    def test_generate_new_then_back_to_saved(self):
        self.client.post(reverse('meal_plan_save'))
        saved_ids = recipe_ids(self.page().context['plan'])
        response = self.client.post(reverse('meal_plan_new'), follow=True)
        self.assertContains(response, 'Here is a new meal plan.')
        self.assertNotEqual(recipe_ids(response.context['plan']), saved_ids)
        self.assertContains(response, 'Back to saved plan')
        response = self.client.post(reverse('meal_plan_discard'), follow=True)
        self.assertEqual(recipe_ids(response.context['plan']), saved_ids)
        self.assertContains(response, 'status-badge--saved')

    def test_actions_need_post(self):
        for name in ('meal_plan_save', 'meal_plan_new', 'meal_plan_discard'):
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 405)
        self.assertFalse(SavedMealPlan.objects.exists())

    def test_actions_need_a_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        for name in ('meal_plan_save', 'meal_plan_new', 'meal_plan_discard'):
            with self.subTest(name):
                self.assertEqual(strict.post(reverse(name)).status_code, 403)
        self.assertFalse(SavedMealPlan.objects.exists())

    def test_actions_need_login_and_onboarding(self):
        self.client.logout()
        response = self.client.post(reverse('meal_plan_save'))
        self.assertRedirects(
            response, f'{reverse("login")}?next={reverse("meal_plan_save")}', fetch_redirect_response=False
        )
        not_onboarded = User.objects.create_user('new', 'new@example.com', PASSWORD)
        UserProfile.objects.create(user=not_onboarded, onboarding_completed=False)
        self.client.force_login(not_onboarded)
        for name in ('meal_plan_save', 'meal_plan_new'):
            with self.subTest(name):
                response = self.client.post(reverse(name))
                self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_actions_report_when_recipes_are_unavailable(self):
        response = self.client.post(reverse('meal_plan_save'), follow=True)
        self.assertContains(response, 'There&#x27;s no meal plan to save right now.')
        self.assertContains(response, 'role="alert"')
        response = self.client.post(reverse('meal_plan_new'), follow=True)
        self.assertContains(response, 'make a new meal plan right now.')
