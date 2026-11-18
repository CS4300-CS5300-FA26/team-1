from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile
from plans.models import WeeklyPlan

from .models import LoggedSet, WorkoutSession
from .test_helpers import onboarded_user


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'])
        self.client.force_login(self.user)

    def open_this_week(self):
        """Open This Week, which saves the week's plan, and return the response."""
        return self.client.get(reverse('this_week'))

    def plan(self) -> WeeklyPlan:
        return WeeklyPlan.objects.get(user=self.user)

    def training_days(self) -> list[int]:
        return [index for index, day in enumerate(self.plan().data['days']) if day['exercises']]

    def start(self, day=None):
        if day is None:
            day = self.training_days()[0]
        response = self.client.post(reverse('workouts_start', args=[day]))
        return response, WorkoutSession.objects.filter(user=self.user, day=day).first()


class AccessTests(TestCase):
    def test_every_page_needs_a_login(self):
        for url in (
            reverse('workouts_start', args=[0]),
            reverse('workouts_session', args=[1]),
            reverse('workouts_history'),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response['Location'])

    def test_starting_needs_onboarding(self):
        user = onboarded_user()
        UserProfile.objects.filter(user=user).update(onboarding_completed=False)
        self.client.force_login(user)
        self.assertRedirects(self.client.post(reverse('workouts_start', args=[0])), reverse('onboarding'))


class ThisWeekButtonTests(LoggedInTestCase):
    def test_each_training_day_on_this_week_has_a_start_button_and_rest_days_do_not(self):
        response = self.open_this_week()
        for day in self.training_days():
            self.assertContains(response, f'action="{reverse("workouts_start", args=[day])}"')
        self.assertContains(response, 'Start workout', count=len(self.training_days()))
        self.assertContains(response, f'href="{reverse("workouts_history")}"')

    def test_a_started_workout_shows_continue_and_a_finished_one_shows_view(self):
        self.open_this_week()
        first, second = self.training_days()[:2]
        _, started = self.start(first)
        _, finished = self.start(second)
        finished.completed_at = finished.started_at
        finished.save()
        response = self.open_this_week()
        self.assertContains(response, 'Continue workout')
        self.assertContains(response, 'In progress')
        self.assertContains(response, 'View workout')
        self.assertContains(response, 'Done')
        self.assertContains(response, f'href="{reverse("workouts_session", args=[started.pk])}"')
        self.assertContains(response, 'Start workout', count=len(self.training_days()) - 2)

    def test_the_starter_plan_offers_no_workouts(self):
        with (
            mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')),
            mock.patch('plans.services.logger'),
        ):
            response = self.open_this_week()
        self.assertContains(response, 'starter plan')
        self.assertNotContains(response, 'Start workout')

    @override_settings(PLANS_WORKOUT_TRACKER=None)
    def test_this_week_still_works_without_the_tracker(self):
        response = self.open_this_week()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Start workout')

    def test_the_header_and_dashboard_lead_to_this_week(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, f'href="{reverse("this_week")}"', count=2)


class StartTests(LoggedInTestCase):
    def test_start_opens_the_session_for_that_day(self):
        self.open_this_week()
        response, session = self.start()
        self.assertRedirects(response, reverse('workouts_session', args=[session.pk]))
        self.assertEqual(session.weekly_plan, self.plan())

    def test_start_is_post_only(self):
        self.open_this_week()
        self.assertEqual(self.client.get(reverse('workouts_start', args=[self.training_days()[0]])).status_code, 405)

    def test_without_a_plan_yet_it_sends_you_to_this_week(self):
        response = self.client.post(reverse('workouts_start', args=[0]), follow=True)
        self.assertRedirects(response, reverse('this_week'))
        self.assertContains(response, 'Open This Week to get your plan')
        self.assertFalse(WorkoutSession.objects.exists())

    def test_a_rest_day_cannot_be_started(self):
        self.open_this_week()
        rest = next(index for index in range(7) if index not in self.training_days())
        response = self.client.post(reverse('workouts_start', args=[rest]), follow=True)
        self.assertRedirects(response, reverse('this_week'))
        self.assertContains(response, 'That day has no workout')
        self.assertFalse(WorkoutSession.objects.exists())

    def test_it_only_ever_uses_your_own_plan(self):
        stranger = onboarded_user(username='stranger', equipment=['dumbbells'])
        self.client.force_login(stranger)
        self.open_this_week()
        self.client.force_login(self.user)
        response = self.client.post(reverse('workouts_start', args=[0]))
        self.assertRedirects(response, reverse('this_week'), fetch_redirect_response=False)
        self.assertFalse(WorkoutSession.objects.filter(user=self.user).exists())


class SessionPageTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.open_this_week()
        _, self.session = self.start()

    def url(self):
        return reverse('workouts_session', args=[self.session.pk])

    def test_shows_each_exercise_with_fields_for_its_sets(self):
        response = self.client.get(self.url())
        for item in self.session.exercises:
            self.assertContains(response, item['name'])
        self.assertContains(response, 'name="reps_1_1"')
        self.assertContains(response, 'name="weight_1_1"')
        self.assertContains(response, 'Back to this week')
        day_name = self.plan().data['days'][self.session.day]['day']
        self.assertContains(response, f'{day_name}&rsquo;s workout')

    def test_save_keeps_the_sets_and_stays_on_the_page(self):
        response = self.client.post(self.url(), {'action': 'save', 'reps_1_1': '10', 'weight_1_1': '25'})
        self.assertRedirects(response, self.url())
        saved = LoggedSet.objects.get(session=self.session)
        self.assertEqual((saved.reps, saved.weight_lb), (10, Decimal('25')))
        self.assertIsNone(WorkoutSession.objects.get(pk=self.session.pk).completed_at)

    def test_finish_marks_it_done_and_goes_to_history(self):
        response = self.client.post(self.url(), {'action': 'finish', 'reps_1_1': '10'}, follow=True)
        self.assertRedirects(response, reverse('workouts_history'))
        self.assertContains(response, 'is done. Nice work.')
        self.assertIsNotNone(WorkoutSession.objects.get(pk=self.session.pk).completed_at)

    def test_finishing_with_nothing_logged_is_refused(self):
        response = self.client.post(self.url(), {'action': 'finish'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Log at least one set before finishing the workout.')
        self.assertIsNone(WorkoutSession.objects.get(pk=self.session.pk).completed_at)

    def test_a_weight_without_reps_is_an_error(self):
        response = self.client.post(self.url(), {'action': 'save', 'weight_1_1': '25'})
        self.assertContains(response, 'Enter the reps for this set, or clear its weight.')
        self.assertFalse(LoggedSet.objects.exists())

    def test_out_of_range_values_are_rejected(self):
        response = self.client.post(self.url(), {'action': 'save', 'reps_1_1': '5000', 'weight_1_1': '-5'})
        self.assertContains(response, 'Some sets need fixing')
        self.assertFalse(LoggedSet.objects.exists())

    def test_values_for_rows_the_workout_does_not_have_are_ignored(self):
        self.client.post(self.url(), {'action': 'save', 'reps_99_1': '10', 'reps_1_99': '10'})
        self.assertFalse(LoggedSet.objects.exists())

    def test_an_unknown_action_changes_nothing(self):
        response = self.client.post(self.url(), {'action': 'delete', 'reps_1_1': '10'}, follow=True)
        self.assertContains(response, 'Choose Save progress or Finish workout.')
        self.assertFalse(LoggedSet.objects.exists())

    def test_timed_exercises_ask_for_seconds_or_minutes(self):
        WorkoutSession.objects.filter(pk=self.session.pk).update(
            exercises=[
                {'name': 'Plank', 'sets': 2, 'reps': '30-45 sec'},
                {'name': 'Brisk Walk or Jog', 'sets': 1, 'reps': '20 min'},
            ]
        )
        response = self.client.get(self.url())
        self.assertContains(response, 'name="seconds_1_2"')
        self.assertContains(response, 'name="minutes_2_1"')
        self.assertNotContains(response, 'name="weight_1_1"')
        self.client.post(self.url(), {'action': 'save', 'seconds_1_1': '40', 'minutes_2_1': '18'})
        self.assertEqual(
            sorted(LoggedSet.objects.values_list('exercise_name', 'seconds', 'minutes')),
            [('Brisk Walk or Jog', None, 18), ('Plank', 40, None)],
        )

    def test_another_users_session_is_not_found(self):
        stranger = onboarded_user(username='stranger')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url(), {'action': 'save', 'reps_1_1': '10'}).status_code, 404)
        self.assertFalse(LoggedSet.objects.exists())


class HistoryPageTests(LoggedInTestCase):
    def test_empty_history_says_so(self):
        self.assertContains(self.client.get(reverse('workouts_history')), 'No finished workouts yet')

    def test_never_shows_another_users_workouts(self):
        stranger = onboarded_user(username='stranger', equipment=['dumbbells'])
        self.client.force_login(stranger)
        self.open_this_week()
        day = next(
            index
            for index, entry in enumerate(WeeklyPlan.objects.get(user=stranger).data['days'])
            if entry['exercises']
        )
        self.client.post(reverse('workouts_start', args=[day]))
        session = WorkoutSession.objects.get(user=stranger)
        session.title = 'Secret strangers workout'
        session.completed_at = session.started_at
        session.save()
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse('workouts_history')), 'Secret strangers workout')


class EndToEndTests(LoggedInTestCase):
    """The whole flow through the real pages: plan, start a session, log sets, and see it in history."""

    def test_plan_start_log_finish_history(self):
        # 1. Plan: This Week (plans app) saves the week's split and offers a Start button per training day.
        this_week = self.open_this_week()
        day = self.training_days()[0]
        entry = self.plan().data['days'][day]
        self.assertContains(this_week, entry['exercises'][0]['name'])

        # 2. Start the session from that button.
        started = self.client.post(reverse('workouts_start', args=[day]), follow=True)
        session = WorkoutSession.objects.get(user=self.user)
        self.assertRedirects(started, reverse('workouts_session', args=[session.pk]))
        self.assertContains(started, entry['name'])

        # 3. Log sets: save part-way, then finish.
        url = reverse('workouts_session', args=[session.pk])
        self.client.post(url, {'action': 'save', 'reps_1_1': '10', 'weight_1_1': '30'})
        self.assertContains(self.open_this_week(), 'Continue workout')
        finished = self.client.post(
            url,
            {'action': 'finish', 'reps_1_1': '10', 'weight_1_1': '30', 'reps_1_2': '8', 'weight_1_2': '35'},
            follow=True,
        )

        # 4. History shows the workout, its sets and volume; This Week shows it done.
        self.assertRedirects(finished, reverse('workouts_history'))
        self.assertContains(finished, entry['name'])
        self.assertContains(finished, '2 sets')
        self.assertContains(finished, '580 lb lifted')
        self.assertContains(self.open_this_week(), 'View workout')
