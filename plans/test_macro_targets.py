"""Tests for the D-4 connector that gives the meal plan this week's macro targets (ADR-012)."""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile
from nutrition.domain import MacroTargets
from nutrition.services import week_start

from .generator import generate_plan
from .macro_targets import PlanMacroTargets
from .models import WeeklyPlan

PASSWORD = 'Correct-Horse-9'
MONDAY = date(2026, 10, 26)
STORED = {'calories': 2100, 'protein': 150, 'carbs': 220, 'fat': 58}


def make_user(username='alice', completed=True, **profile_fields):
    user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
    fields = (
        {
            'goal': 'build_muscle',
            'height_inches': 70,
            'weight': Decimal('180.50'),
            'experience_level': 'intermediate',
            'weekly_food_budget': Decimal('85.50'),
            'equipment': ['dumbbells'],
            'planned_meals': ['breakfast', 'lunch', 'dinner'],
        }
        if completed
        else {}
    )
    fields.update(profile_fields)
    UserProfile.objects.create(user=user, onboarding_completed=completed, **fields)
    return user


def as_targets(macros):
    return MacroTargets(protein_g=macros['protein'], carbs_g=macros['carbs'], fat_g=macros['fat'])


class PlanMacroTargetsTests(TestCase):
    def setUp(self):
        self.provider = PlanMacroTargets()

    def week(self, user):
        targets = self.provider.weekly_targets(user, MONDAY)
        assert targets is not None
        return list(targets)

    def test_seven_days_of_the_saved_plans_targets(self):
        user = make_user()
        WeeklyPlan.objects.create(user=user, week_start=MONDAY, data={'days': [], 'macros': STORED})
        with mock.patch('plans.macro_targets.generate_plan', side_effect=AssertionError('regenerated')):
            targets = self.week(user)
        self.assertEqual(targets, [as_targets(STORED)] * 7)

    def test_without_a_saved_plan_it_calculates_the_same_targets_and_saves_nothing(self):
        user = make_user()
        expected = as_targets(generate_plan(user.userprofile)['macros'])
        self.assertEqual(self.week(user), [expected] * 7)
        self.assertFalse(WeeklyPlan.objects.exists())

    def test_another_weeks_plan_is_not_used(self):
        user = make_user()
        WeeklyPlan.objects.create(user=user, week_start=MONDAY - timedelta(days=7), data={'macros': STORED})
        self.assertNotEqual(self.week(user)[0], as_targets(STORED))

    def test_another_users_plan_is_never_used(self):
        bob = make_user('bob')
        WeeklyPlan.objects.create(user=bob, week_start=MONDAY, data={'macros': STORED})
        alice = make_user('alice', completed=False)
        self.assertIsNone(self.provider.weekly_targets(alice, MONDAY))

    def test_none_before_onboarding(self):
        self.assertIsNone(self.provider.weekly_targets(make_user(completed=False), MONDAY))

    def test_none_when_the_profile_cant_make_a_plan(self):
        self.assertIsNone(self.provider.weekly_targets(make_user(goal=''), MONDAY))
        self.assertFalse(WeeklyPlan.objects.exists())

    def test_unusable_saved_targets_are_logged_and_ignored(self):
        user = make_user()
        WeeklyPlan.objects.create(user=user, week_start=MONDAY, data={'macros': {**STORED, 'carbs': 0}})
        with self.assertLogs('plans.macro_targets', level='WARNING'):
            self.assertIsNone(self.provider.weekly_targets(user, MONDAY))


class MealPlanUsesPlanTargetsTests(TestCase):
    """/meal-plan/ with the real NUTRITION_MACRO_TARGETS_PROVIDER setting (no override)."""

    def setUp(self):
        self.user = make_user()
        self.assertTrue(self.client.login(username='alice', password=PASSWORD))

    def test_meal_plan_aims_at_the_targets_on_the_nutrition_page(self):
        shown = self.client.get(reverse('nutrition')).context['macros']
        response = self.client.get(reverse('meal_plan'))
        result = response.context['result']
        self.assertTrue(result.personal_targets)
        self.assertEqual(result.plan.daily_targets, tuple([as_targets(shown)] * 7))
        self.assertContains(response, 'Meals are matched to your daily macro targets')
        self.assertNotContains(response, "macro targets aren't ready")

    def test_meal_plan_uses_this_weeks_saved_plan(self):
        WeeklyPlan.objects.create(
            user=self.user, week_start=week_start(timezone.localdate()), data={'days': [], 'macros': STORED}
        )
        result = self.client.get(reverse('meal_plan')).context['result']
        self.assertEqual(result.plan.daily_targets, tuple([as_targets(STORED)] * 7))
