from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile

from . import services
from .models import LoggedSet, PlannedExercise, WorkoutSession
from .test_helpers import onboarded_user


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'])
        self.client.force_login(self.user)
        self.profile = UserProfile.objects.get(user=self.user)

    def start(self, user=None, client=None):
        user = user or self.user
        plan = services.current_plan(user, UserProfile.objects.get(user=user))
        workout = plan.workouts.order_by('day')[0]
        return workout, services.start_session(user, workout)

    def row_data(self, session, reps='10', weight='25'):
        """POST data filling set 1 of every strength exercise."""
        data = {}
        for log in services.session_log(session):
            if not log.planned.is_timed:
                data[f'reps_{log.planned.pk}_1'] = reps
                data[f'weight_{log.planned.pk}_1'] = weight
        return data


class AccessTests(TestCase):
    def test_every_workout_page_needs_a_login(self):
        urls = [
            reverse('workouts_this_week'),
            reverse('workouts_history'),
            reverse('workouts_session', args=[1]),
            reverse('workouts_start', args=[1]),
            reverse('workouts_new'),
            reverse('workouts_preferences'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f'{reverse("login")}?next={url}')

    def test_someone_who_has_not_onboarded_is_sent_to_the_questionnaire(self):
        self.client.force_login(User.objects.create_user(username='new'))
        self.assertRedirects(self.client.get(reverse('workouts_this_week')), reverse('onboarding'))
        self.assertRedirects(self.client.post(reverse('workouts_new')), reverse('onboarding'))
        self.assertRedirects(
            self.client.post(reverse('workouts_preferences'), {'days_per_week': '4'}), reverse('onboarding')
        )


class ThisWeekTests(LoggedInTestCase):
    def test_shows_the_week_with_workouts_and_rest_days(self):
        response = self.client.get(reverse('workouts_this_week'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Full body A')
        self.assertContains(response, 'Rest day')
        self.assertContains(response, 'Start workout')
        self.assertContains(response, 'Dumbbells')
        self.assertContains(response, 'not medical advice')

    def test_a_started_workout_offers_to_continue(self):
        _, session = self.start()
        response = self.client.get(reverse('workouts_this_week'))
        self.assertContains(response, 'In progress')
        self.assertContains(response, reverse('workouts_session', args=[session.pk]))

    def test_get_is_not_allowed_on_state_changing_urls(self):
        for url in (reverse('workouts_new'), reverse('workouts_preferences'), reverse('workouts_start', args=[1])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_state_changing_posts_need_a_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        for url in (reverse('workouts_new'), reverse('workouts_preferences'), reverse('workouts_start', args=[1])):
            with self.subTest(url=url):
                self.assertEqual(strict.post(url, {'days_per_week': '4'}).status_code, 403)

    def test_choosing_training_days_remakes_the_plan(self):
        response = self.client.post(reverse('workouts_preferences'), {'days_per_week': '5'}, follow=True)
        self.assertContains(response, 'now has 5 training days')
        self.assertEqual(
            len(response.context['days']) - sum(1 for d in response.context['days'] if d.status == 'rest'), 5
        )

    def test_an_invalid_day_count_is_refused(self):
        for value in ('7', 'abc', ''):
            with self.subTest(value=value):
                response = self.client.post(reverse('workouts_preferences'), {'days_per_week': value}, follow=True)
                self.assertContains(response, 'Choose 3, 4, or 5')

    def test_generate_a_new_plan(self):
        response = self.client.post(reverse('workouts_new'), follow=True)
        self.assertContains(response, 'new workout plan')


class StartTests(LoggedInTestCase):
    def test_starting_opens_the_session_and_twice_is_the_same_session(self):
        plan = services.current_plan(self.user, self.profile)
        workout = plan.workouts.order_by('day')[0]
        first = self.client.post(reverse('workouts_start', args=[workout.pk]))
        second = self.client.post(reverse('workouts_start', args=[workout.pk]))
        session = WorkoutSession.objects.get()
        self.assertRedirects(first, reverse('workouts_session', args=[session.pk]))
        self.assertRedirects(second, reverse('workouts_session', args=[session.pk]))

    def test_another_users_workout_is_not_found(self):
        stranger = onboarded_user(username='stranger')
        plan = services.current_plan(stranger, UserProfile.objects.get(user=stranger))
        workout = plan.workouts.all()[0]
        response = self.client.post(reverse('workouts_start', args=[workout.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(WorkoutSession.objects.exists())

    def test_a_past_weeks_workout_cannot_be_started(self):
        last_week = timezone.localdate() - timedelta(days=7)
        plan = services.current_plan(self.user, self.profile, today=last_week)
        workout = plan.workouts.all()[0]
        response = self.client.post(reverse('workouts_start', args=[workout.pk]), follow=True)
        self.assertContains(response, 'past week')
        self.assertFalse(WorkoutSession.objects.exists())


class SessionTests(LoggedInTestCase):
    def test_shows_each_exercise_with_how_to_and_rest_timer(self):
        _, session = self.start()
        response = self.client.get(reverse('workouts_session', args=[session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'How to do it')
        self.assertContains(response, 'data-rest-start')
        self.assertContains(response, 'Finish workout')
        # No media: the dataset's Gym visual images and videos are not used.
        self.assertNotContains(response, 'gymvisual')
        self.assertNotContains(response, '.gif')

    def test_another_users_session_is_not_found_to_read_or_change(self):
        stranger = onboarded_user(username='stranger')
        _, theirs = self.start(user=stranger)
        url = reverse('workouts_session', args=[theirs.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'action': 'finish'}).status_code, 404)
        self.assertFalse(LoggedSet.objects.exists())

    def test_save_progress_keeps_the_sets_and_stays_on_the_page(self):
        _, session = self.start()
        response = self.client.post(
            reverse('workouts_session', args=[session.pk]), {**self.row_data(session), 'action': 'save'}, follow=True
        )
        self.assertContains(response, 'Progress saved')
        self.assertGreater(LoggedSet.objects.filter(session=session).count(), 0)
        session.refresh_from_db()
        self.assertIsNone(session.completed_at)
        # The saved values come back in the form.
        self.assertContains(response, 'value="25.0"')

    def test_finishing_completes_and_goes_to_history(self):
        _, session = self.start()
        response = self.client.post(
            reverse('workouts_session', args=[session.pk]), {**self.row_data(session), 'action': 'finish'}
        )
        self.assertRedirects(response, reverse('workouts_history'))
        session.refresh_from_db()
        self.assertIsNotNone(session.completed_at)

    def test_finishing_with_nothing_logged_is_refused(self):
        _, session = self.start()
        response = self.client.post(reverse('workouts_session', args=[session.pk]), {'action': 'finish'})
        self.assertContains(response, 'Log at least one set')
        session.refresh_from_db()
        self.assertIsNone(session.completed_at)

    def test_a_weight_without_reps_is_an_error_naming_the_set(self):
        workout, session = self.start()
        item = workout.exercises.all()[0]
        response = self.client.post(
            reverse('workouts_session', args=[session.pk]),
            {f'weight_{item.pk}_1': '30', 'action': 'save'},
        )
        self.assertContains(response, 'Enter the reps for this set')
        self.assertContains(response, 'role="alert"')
        self.assertFalse(LoggedSet.objects.exists())

    def test_out_of_range_numbers_are_refused(self):
        workout, session = self.start()
        item = workout.exercises.all()[0]
        for field, value in (
            ('reps', '0'),
            ('reps', '201'),
            ('reps', 'x'),
            ('weight', '-5'),
            ('weight', '2001'),
            ('weight', '1.55'),
        ):
            with self.subTest(field=field, value=value):
                data = {f'reps_{item.pk}_1': '5', f'{field}_{item.pk}_1': value, 'action': 'save'}
                response = self.client.post(reverse('workouts_session', args=[session.pk]), data)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(LoggedSet.objects.exists())

    def test_fields_for_rows_that_are_not_in_the_workout_are_ignored(self):
        workout, session = self.start()
        other_item = PlannedExercise.objects.exclude(workout=workout)[0]
        item = workout.exercises.all()[0]
        data = {
            f'reps_{other_item.pk}_1': '10',  # another workout's exercise
            f'reps_{item.pk}_99': '10',  # a set the plan doesn't have
            f'reps_{item.pk}_1': '8',
            'action': 'save',
        }
        self.client.post(reverse('workouts_session', args=[session.pk]), data)
        self.assertEqual(list(LoggedSet.objects.values_list('exercise_id', 'set_number')), [(item.exercise_id, 1)])

    def test_an_unknown_action_is_refused(self):
        _, session = self.start()
        response = self.client.post(reverse('workouts_session', args=[session.pk]), {'action': 'delete'}, follow=True)
        self.assertContains(response, 'Choose Save progress or Finish workout')

    def test_a_replaced_plan_leaves_a_read_only_page(self):
        _, session = self.start()
        services.new_plan(self.user, self.profile)
        response = self.client.get(reverse('workouts_session', args=[session.pk]))
        self.assertContains(response, 'nothing left to log')

    def test_cardio_is_logged_in_minutes(self):
        self.profile.goal = 'lose_weight'
        self.profile.save()
        workout, session = self.start()
        cardio = workout.exercises.get(minutes__isnull=False)
        response = self.client.post(
            reverse('workouts_session', args=[session.pk]), {f'minutes_{cardio.pk}_1': '12', 'action': 'finish'}
        )
        self.assertRedirects(response, reverse('workouts_history'))
        self.assertEqual(LoggedSet.objects.get().minutes, 12)


class HistoryTests(LoggedInTestCase):
    def test_shows_progress_and_finished_workouts(self):
        _, session = self.start()
        self.client.post(reverse('workouts_session', args=[session.pk]), {**self.row_data(session), 'action': 'finish'})
        response = self.client.get(reverse('workouts_history'))
        self.assertContains(response, 'Last 8 weeks')
        self.assertContains(response, session.title)
        self.assertEqual(response.context['weeks'][0].completed, 1)
        self.assertGreater(response.context['weeks'][0].volume_lb, Decimal(0))

    def test_empty_history_says_so(self):
        self.assertContains(self.client.get(reverse('workouts_history')), 'No finished workouts yet')

    def test_never_shows_another_users_workouts(self):
        stranger = onboarded_user(username='stranger')
        _, theirs = self.start(user=stranger)
        theirs.completed_at = timezone.now()
        theirs.title = 'Secret strangers workout'
        theirs.save()
        response = self.client.get(reverse('workouts_history'))
        self.assertNotContains(response, 'Secret strangers workout')


class NavigationTests(LoggedInTestCase):
    def test_the_header_and_dashboard_link_to_workouts(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, f'href="{reverse("workouts_this_week")}"', count=2)

    def test_the_meal_plan_unavailable_page_links_to_this_week(self):
        from django.conf import settings

        self.assertEqual(settings.NUTRITION_WORKOUTS_LINK['url_name'], 'workouts_this_week')
