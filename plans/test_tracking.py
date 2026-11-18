from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .tracking import DayAction, WorkoutLinks, workout_links

MONDAY = date(2026, 11, 2)
DAYS = [{'day': 'Monday', 'name': 'Full Body A', 'exercises': [{'name': 'Push-Up', 'sets': 3, 'reps': '8-12'}]}]


class FixedTracker:
    def links(self, user, week_start, days):
        return WorkoutLinks(days={0: DayAction(label='Start workout', url='/go/', post=True)}, history_url='/h/')


class BrokenTracker:
    def links(self, user, week_start, days):
        raise RuntimeError('tracker down')


class WrongShapeTracker:
    def links(self, user, week_start, days):
        return {'0': 'start'}


class WorkoutLinksTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='lifter')

    @override_settings(PLANS_WORKOUT_TRACKER='plans.test_tracking.FixedTracker')
    def test_uses_the_tracker_named_in_settings(self):
        links = workout_links(self.user, MONDAY, DAYS)
        self.assertEqual(links.days[0].label, 'Start workout')
        self.assertEqual(links.history_url, '/h/')

    @override_settings(PLANS_WORKOUT_TRACKER=None)
    def test_with_no_tracker_there_are_no_links(self):
        self.assertEqual(workout_links(self.user, MONDAY, DAYS), WorkoutLinks())

    @override_settings(PLANS_WORKOUT_TRACKER='plans.test_tracking.BrokenTracker')
    def test_a_failing_tracker_is_logged_and_gives_no_links(self):
        with mock.patch('plans.tracking.logger') as logger:
            self.assertEqual(workout_links(self.user, MONDAY, DAYS), WorkoutLinks())
        logger.exception.assert_called_once()

    @override_settings(PLANS_WORKOUT_TRACKER='plans.test_tracking.WrongShapeTracker')
    def test_a_tracker_returning_the_wrong_shape_gives_no_links(self):
        self.assertEqual(workout_links(self.user, MONDAY, DAYS), WorkoutLinks())

    @override_settings(PLANS_WORKOUT_TRACKER='plans.test_tracking.BrokenTracker')
    def test_this_week_still_shows_the_plan_when_the_tracker_fails(self):
        from core.models import UserProfile

        UserProfile.objects.create(
            user=self.user,
            onboarding_completed=True,
            goal='build_muscle',
            experience_level='beginner',
            equipment=['none'],
            height_inches=70,
            weight=180,
            weekly_food_budget=50,
        )
        self.client.force_login(self.user)
        with mock.patch('plans.tracking.logger'):
            response = self.client.get('/plans/this-week/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Push-Up')
        self.assertNotContains(response, 'Start workout')
