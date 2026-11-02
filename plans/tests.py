"""Tests for the weekly plan and macro targets (the generator, the starter fallback, and the pages).

The Gherkin scenarios for this story are in features/weekly_plan.feature.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import UserProfile

from . import generator
from .generator import PlanGenerationError, calculate_macros, generate_plan
from .models import WeeklyPlan
from .services import get_weekly_plan, week_start_for
from .starter import starter_plan

PASSWORD = 'Correct-Horse-9'


def make_profile(**overrides):
    """A stand-in for UserProfile (the generator only reads attributes)."""
    fields = {
        'goal': 'build_muscle', 'experience_level': 'beginner', 'weight': Decimal('180'),
        'height_inches': 70, 'age': None, 'equipment': ['dumbbells'],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def training_days(plan):
    return [day for day in plan['days'] if day['exercises']]


def exercise_names(plan):
    return {exercise['name'] for day in plan['days'] for exercise in day['exercises']}


class GeneratorStructureTests(SimpleTestCase):
    def test_plan_covers_seven_days_monday_first(self):
        days = generate_plan(make_profile())['days']
        self.assertEqual([d['day'] for d in days],
                         ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])

    def test_training_days_follow_experience_level(self):
        for level, expected in (('beginner', 3), ('intermediate', 4), ('advanced', 5)):
            plan = generate_plan(make_profile(experience_level=level))
            self.assertEqual(len(training_days(plan)), expected, level)

    def test_rest_days_have_no_exercises(self):
        plan = generate_plan(make_profile())
        rest = [d for d in plan['days'] if d['name'] == 'Rest']
        self.assertEqual(len(rest), 4)
        self.assertTrue(all(d['exercises'] == [] for d in rest))

    def test_every_exercise_has_name_sets_and_reps(self):
        for level in ('beginner', 'intermediate', 'advanced'):
            for day in training_days(generate_plan(make_profile(experience_level=level))):
                for exercise in day['exercises']:
                    self.assertTrue(exercise['name'])
                    self.assertGreater(exercise['sets'], 0)
                    self.assertTrue(exercise['reps'])

    def test_advanced_lifters_get_more_sets(self):
        beginner = generate_plan(make_profile(experience_level='beginner'))
        advanced = generate_plan(make_profile(experience_level='advanced'))
        self.assertEqual(training_days(beginner)[0]['exercises'][0]['sets'], 3)
        self.assertEqual(training_days(advanced)[0]['exercises'][0]['sets'], 4)

    def test_reps_follow_goal(self):
        endurance = generate_plan(make_profile(goal='endurance'))
        muscle = generate_plan(make_profile(goal='build_muscle'))
        self.assertEqual(training_days(endurance)[0]['exercises'][0]['reps'], '15-20')
        self.assertEqual(training_days(muscle)[0]['exercises'][0]['reps'], '8-12')

    def test_cardio_added_for_weight_loss_and_endurance_only(self):
        for goal, has_cardio in (('lose_weight', True), ('endurance', True),
                                 ('build_muscle', False), ('maintain', False)):
            plan = generate_plan(make_profile(goal=goal, equipment=['cardio']))
            names = exercise_names(plan)
            self.assertEqual('Treadmill or Bike Intervals' in names, has_cardio, goal)

    def test_cardio_falls_back_to_walking_without_cardio_equipment(self):
        plan = generate_plan(make_profile(goal='lose_weight', equipment=['dumbbells']))
        self.assertIn('Brisk Walk or Jog', exercise_names(plan))


class GeneratorEquipmentTests(SimpleTestCase):
    def test_every_movement_has_a_bodyweight_fallback(self):
        for movement, options in generator.EXERCISES.items():
            self.assertEqual(options[-1][0], 'none', movement)

    def test_no_equipment_gives_bodyweight_exercises(self):
        names = exercise_names(generate_plan(make_profile(equipment=['none'])))
        self.assertIn('Push-Up', names)
        self.assertIn('Bodyweight Squat', names)
        self.assertNotIn('Barbell Bench Press', names)

    def test_barbell_gives_barbell_lifts(self):
        names = exercise_names(generate_plan(make_profile(equipment=['barbell'])))
        self.assertIn('Barbell Bench Press', names)
        self.assertIn('Barbell Back Squat', names)

    def test_dumbbells_give_dumbbell_lifts(self):
        names = exercise_names(generate_plan(make_profile(equipment=['dumbbells'])))
        self.assertIn('Dumbbell Bench Press', names)
        self.assertIn('Goblet Squat', names)

    def test_only_cardio_equipment_still_gets_a_full_strength_plan(self):
        plan = generate_plan(make_profile(equipment=['cardio']))
        self.assertEqual(len(training_days(plan)), 3)
        self.assertIn('Push-Up', exercise_names(plan))

    def test_unknown_equipment_is_ignored(self):
        names = exercise_names(generate_plan(make_profile(equipment=['trampoline'])))
        self.assertIn('Push-Up', names)


class MacroTests(SimpleTestCase):
    def macros(self, goal, **kw):
        args = dict(weight_lb=180, height_in=70, age=25, training_days=4)
        args.update(kw)
        return calculate_macros(goal, **args)

    def test_calories_ordered_by_goal(self):
        lose = self.macros('lose_weight')['calories']
        maintain = self.macros('maintain')['calories']
        build = self.macros('build_muscle')['calories']
        self.assertLess(lose, maintain)
        self.assertLess(maintain, build)

    def test_macros_add_up_to_calories(self):
        for goal in generator.GOAL_REPS:
            m = self.macros(goal)
            total = m['protein'] * 4 + m['carbs'] * 4 + m['fat'] * 9
            self.assertAlmostEqual(total, m['calories'], delta=20, msg=goal)

    def test_more_training_days_means_more_calories(self):
        self.assertLess(self.macros('maintain', training_days=3)['calories'],
                        self.macros('maintain', training_days=5)['calories'])

    def test_calories_never_drop_below_the_floor(self):
        m = self.macros('lose_weight', weight_lb=50, height_in=36, training_days=3)
        self.assertEqual(m['calories'], generator.MIN_CALORIES)

    def test_protein_is_capped_for_very_heavy_users(self):
        m = self.macros('lose_weight', weight_lb=700, height_in=60, age=80, training_days=3)
        self.assertLessEqual(m['protein'] * 4, m['calories'] * generator.MAX_PROTEIN_SHARE + 4)
        self.assertGreaterEqual(m['carbs'], 0)

    def test_plan_includes_macros_with_all_four_values(self):
        macros = generate_plan(make_profile())['macros']
        self.assertEqual(set(macros), {'calories', 'protein', 'carbs', 'fat'})


class GeneratorValidationTests(SimpleTestCase):
    def test_missing_goal_raises(self):
        with self.assertRaises(PlanGenerationError):
            generate_plan(make_profile(goal=''))

    def test_missing_experience_level_raises(self):
        with self.assertRaises(PlanGenerationError):
            generate_plan(make_profile(experience_level=''))

    def test_missing_weight_or_height_raises(self):
        with self.assertRaises(PlanGenerationError):
            generate_plan(make_profile(weight=None))
        with self.assertRaises(PlanGenerationError):
            generate_plan(make_profile(height_inches=None))


class StarterPlanTests(SimpleTestCase):
    def test_starter_plan_is_a_full_week_with_macros(self):
        plan = starter_plan()
        self.assertEqual(len(plan['days']), 7)
        self.assertEqual(len(training_days(plan)), 3)
        self.assertEqual(set(plan['macros']), {'calories', 'protein', 'carbs', 'fat'})

    def test_callers_cannot_change_the_shared_starter_plan(self):
        starter_plan()['days'][0]['exercises'].clear()
        self.assertTrue(starter_plan()['days'][0]['exercises'])


class WeekStartTests(SimpleTestCase):
    def test_week_starts_on_monday(self):
        self.assertEqual(week_start_for(date(2026, 11, 1)), date(2026, 10, 26))  # a Sunday
        self.assertEqual(week_start_for(date(2026, 10, 26)), date(2026, 10, 26))  # the Monday


class PlanTestBase(TestCase):
    def make_user(self, username='alice', completed=True, **profile_fields):
        user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
        fields = {
            'goal': 'build_muscle', 'height_inches': 70, 'weight': Decimal('180.50'),
            'experience_level': 'intermediate', 'weekly_food_budget': Decimal('85.50'),
            'equipment': ['dumbbells'],
        } if completed else {}
        fields.update(profile_fields)
        UserProfile.objects.create(user=user, onboarding_completed=completed, **fields)
        return user

    def log_in(self, user):
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))


class WeeklyPlanServiceTests(PlanTestBase):
    def test_plan_is_saved_once_and_reused(self):
        user = self.make_user()
        profile = user.userprofile
        first, first_starter = get_weekly_plan(profile, date(2026, 10, 27))
        with mock.patch('plans.services.generate_plan', side_effect=AssertionError('regenerated')):
            second, _ = get_weekly_plan(profile, date(2026, 10, 30))  # same week
        self.assertFalse(first_starter)
        self.assertEqual(first, second)
        self.assertEqual(WeeklyPlan.objects.filter(user=user).count(), 1)

    def test_a_new_week_gets_a_new_plan(self):
        user = self.make_user()
        get_weekly_plan(user.userprofile, date(2026, 10, 27))
        get_weekly_plan(user.userprofile, date(2026, 11, 3))
        self.assertEqual(WeeklyPlan.objects.filter(user=user).count(), 2)

    def test_generator_failure_returns_starter_and_saves_nothing(self):
        user = self.make_user()
        with mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')):
            with self.assertLogs('plans.services', level='ERROR'):
                plan, is_starter = get_weekly_plan(user.userprofile, date(2026, 10, 27))
        self.assertTrue(is_starter)
        self.assertEqual(plan, starter_plan())
        self.assertEqual(WeeklyPlan.objects.count(), 0)

    def test_incomplete_profile_falls_back_to_starter(self):
        user = self.make_user(goal='')
        with self.assertLogs('plans.services', level='ERROR'):
            _, is_starter = get_weekly_plan(user.userprofile, date(2026, 10, 27))
        self.assertTrue(is_starter)


class ThisWeekViewTests(PlanTestBase):
    def test_login_required(self):
        for name in ('this_week', 'nutrition'):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, f"{reverse('login')}?next={reverse(name)}",
                                 fetch_redirect_response=False)

    def test_user_who_has_not_onboarded_is_sent_to_onboarding(self):
        self.log_in(self.make_user(completed=False))
        for name in ('this_week', 'nutrition'):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_shows_full_week_with_exercises_sets_and_reps(self):
        self.log_in(self.make_user())
        response = self.client.get(reverse('this_week'))
        self.assertEqual(response.status_code, 200)
        days = response.context['days']
        self.assertEqual(len(days), 7)
        self.assertEqual(len([d for d in days if d['exercises']]), 4)  # intermediate
        self.assertContains(response, 'Dumbbell Bench Press')
        self.assertContains(response, '<th>Sets</th>')
        self.assertContains(response, '<th>Reps</th>')
        self.assertContains(response, 'Rest day')
        self.assertNotContains(response, 'starter plan')

    def test_exactly_one_day_is_marked_today(self):
        self.log_in(self.make_user())
        days = self.client.get(reverse('this_week')).context['days']
        self.assertEqual(len([d for d in days if d['is_today']]), 1)

    def test_shows_todays_macro_targets(self):
        self.log_in(self.make_user())
        response = self.client.get(reverse('this_week'))
        macros = response.context['macros']
        self.assertContains(response, "Today's macro targets")
        self.assertContains(response, f"{macros['calories']}")
        self.assertContains(response, f"{macros['protein']} g")

    def test_plan_is_saved_and_reused_across_visits(self):
        user = self.make_user()
        self.log_in(user)
        self.client.get(reverse('this_week'))
        self.client.get(reverse('this_week'))
        self.client.get(reverse('nutrition'))
        self.assertEqual(WeeklyPlan.objects.filter(user=user).count(), 1)

    def test_users_only_see_their_own_plan(self):
        alice = self.make_user('alice', equipment=['barbell'])
        self.make_user('bob', equipment=['none'])
        self.log_in(alice)
        self.client.get(reverse('this_week'))
        self.client.logout()
        self.log_in(User.objects.get(username='bob'))
        response = self.client.get(reverse('this_week'))
        self.assertContains(response, 'Push-Up')
        self.assertNotContains(response, 'Barbell Bench Press')
        self.assertEqual(WeeklyPlan.objects.count(), 2)

    def test_generator_down_shows_starter_plan_and_macros(self):
        self.log_in(self.make_user())
        with mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')):
            with self.assertLogs('plans.services', level='ERROR'):
                response = self.client.get(reverse('this_week'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'starter plan')
        self.assertContains(response, 'Starter Full Body')
        self.assertContains(response, "Today's macro targets")
        self.assertEqual(len(response.context['days']), 7)
        self.assertEqual(WeeklyPlan.objects.count(), 0)

    def test_generator_recovers_on_the_next_visit(self):
        self.log_in(self.make_user())
        with mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')):
            with self.assertLogs('plans.services', level='ERROR'):
                self.client.get(reverse('this_week'))
        response = self.client.get(reverse('this_week'))
        self.assertNotContains(response, 'starter plan')
        self.assertContains(response, 'Dumbbell Bench Press')


class NutritionViewTests(PlanTestBase):
    def test_shows_daily_macro_targets_matching_this_weeks_plan(self):
        self.log_in(self.make_user())
        week = self.client.get(reverse('this_week')).context['macros']
        response = self.client.get(reverse('nutrition'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['macros'], week)
        for label in ('calories', 'protein', 'carbs', 'fat'):
            self.assertContains(response, label)

    def test_generator_down_shows_starter_targets(self):
        self.log_in(self.make_user())
        with mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')):
            with self.assertLogs('plans.services', level='ERROR'):
                response = self.client.get(reverse('nutrition'))
        self.assertContains(response, 'starter targets')
        self.assertEqual(response.context['macros'], starter_plan()['macros'])


class DashboardLinkTests(PlanTestBase):
    def test_dashboard_links_to_this_week_and_nutrition(self):
        self.log_in(self.make_user())
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, reverse('this_week'))
        self.assertContains(response, reverse('nutrition'))
