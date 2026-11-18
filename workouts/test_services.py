from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from core.models import UserProfile
from plans.models import WeeklyPlan
from plans.services import get_weekly_plan, switch_split

from . import services
from .domain import MINUTES, REPS, SECONDS, parse_target
from .models import LoggedSet, WorkoutSession
from .test_helpers import onboarded_user

MONDAY = date(2026, 11, 2)  # a Monday


def saved_plan(user, today=MONDAY) -> WeeklyPlan:
    """The user's weekly plan from the plans app, saved the way opening This Week saves it."""
    get_weekly_plan(UserProfile.objects.get(user=user), today)
    return WeeklyPlan.objects.get(user=user, week_start=services.week_start_for(today))


def first_training_day(plan: WeeklyPlan) -> int:
    return next(index for index, day in enumerate(plan.data['days']) if day['exercises'])


class TargetTests(SimpleTestCase):
    def test_a_rep_range(self):
        target = parse_target(3, '8-12')
        self.assertEqual((target.kind, target.sets, target.low, target.high), (REPS, 3, 8, 12))
        self.assertEqual(target.describe(), '3 sets of 8-12 reps')
        self.assertEqual(target.rest_seconds, 90)

    def test_lighter_sets_rest_less(self):
        self.assertEqual(parse_target(3, '15-20').rest_seconds, 60)

    def test_a_hold_in_seconds(self):
        target = parse_target(3, '30-45 sec')
        self.assertEqual((target.kind, target.low, target.high), (SECONDS, 30, 45))
        self.assertEqual(target.describe(), '3 sets of 30-45 seconds')
        self.assertEqual(target.rest_seconds, 45)

    def test_cardio_in_minutes_is_one_block_with_no_rest(self):
        target = parse_target(1, '20 min')
        self.assertEqual((target.kind, target.sets, target.low), (MINUTES, 1, 20))
        self.assertIsNone(target.rest_seconds)
        self.assertEqual(target.describe(), '20 min at a steady pace')

    def test_a_single_number_and_an_unknown_format_are_still_reps(self):
        self.assertEqual((parse_target(2, '10').low, parse_target(2, '10').high), (10, 10))
        odd = parse_target(2, 'to failure')
        self.assertEqual((odd.kind, odd.low, odd.sets), (REPS, None, 2))
        self.assertEqual(odd.describe(), '2 sets of to failure reps')

    def test_sets_are_at_least_one(self):
        self.assertEqual(parse_target(0, '8-12').sets, 1)


class StartSessionTests(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'])
        self.plan = saved_plan(self.user)
        self.day = first_training_day(self.plan)

    def test_copies_the_days_workout_from_the_weekly_plan(self):
        session = services.start_session(self.user, self.plan, self.day, today=MONDAY)
        entry = self.plan.data['days'][self.day]
        self.assertEqual(session.title, entry['name'])
        self.assertEqual([e['name'] for e in session.exercises], [e['name'] for e in entry['exercises']])
        self.assertEqual((session.weekly_plan, session.day, session.performed_on), (self.plan, self.day, MONDAY))

    def test_starting_twice_gives_the_same_session(self):
        first = services.start_session(self.user, self.plan, self.day)
        second = services.start_session(self.user, self.plan, self.day)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(WorkoutSession.objects.count(), 1)

    def test_the_database_allows_one_session_per_day_of_a_plan(self):
        services.start_session(self.user, self.plan, self.day)
        with self.assertRaises(IntegrityError):
            WorkoutSession.objects.create(
                user=self.user, weekly_plan=self.plan, day=self.day, title='Again', performed_on=MONDAY
            )

    def test_a_rest_day_or_a_day_outside_the_week_cannot_be_started(self):
        rest = next(index for index, day in enumerate(self.plan.data['days']) if not day['exercises'])
        for day in (rest, 7, -1):
            with self.subTest(day=day), self.assertRaises(services.NotATrainingDay):
                services.start_session(self.user, self.plan, day)

    def test_another_users_plan_cannot_be_started(self):
        stranger = onboarded_user(username='stranger')
        with self.assertRaises(services.NotATrainingDay):
            services.start_session(stranger, self.plan, self.day)

    def test_switching_the_split_later_leaves_a_started_workout_alone(self):
        session = services.start_session(self.user, self.plan, self.day, today=MONDAY)
        before = list(session.exercises)
        switch_split(UserProfile.objects.get(user=self.user), 'push_pull_legs', today=MONDAY)
        session.refresh_from_db()
        self.assertEqual(session.exercises, before)

    def test_current_weekly_plan_reads_but_never_makes_a_plan(self):
        other = onboarded_user(username='new')
        self.assertIsNone(services.current_weekly_plan(other, MONDAY))
        self.assertFalse(WeeklyPlan.objects.filter(user=other).exists())
        self.assertEqual(services.current_weekly_plan(self.user, MONDAY + timedelta(days=4)), self.plan)


class LoggingTests(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'], goal='lose_weight')
        self.plan = saved_plan(self.user)
        self.day = first_training_day(self.plan)
        self.session = services.start_session(self.user, self.plan, self.day, today=MONDAY)

    def logs(self):
        return services.session_log(self.session)

    def test_one_row_per_planned_set_and_the_right_kind_for_each_exercise(self):
        kinds = {log.name: log.target.kind for log in self.logs()}
        for item in self.session.exercises:
            log = next(entry for entry in self.logs() if entry.name == item['name'])
            self.assertEqual(len(log.rows), log.target.sets)
        # lose_weight days end with cardio in minutes; the plan's core work is a timed hold.
        self.assertIn(MINUTES, kinds.values())

    def test_saves_reps_and_weight_and_clears_a_set_that_is_emptied(self):
        names = {log.position: log.name for log in self.logs()}
        services.save_session(self.session, {(1, 1): (10, Decimal('25'), None, None)}, names, finish=False)
        saved = LoggedSet.objects.get(session=self.session)
        self.assertEqual((saved.position, saved.exercise_name, saved.reps, saved.weight_lb), (1, names[1], 10, 25))
        services.save_session(self.session, {(1, 1): (None, None, None, None)}, names, finish=False)
        self.assertFalse(LoggedSet.objects.exists())

    def test_seconds_and_minutes_never_carry_a_weight(self):
        names = {log.position: log.name for log in self.logs()}
        services.save_session(
            self.session, {(1, 1): (None, Decimal('20'), 40, None), (2, 1): (None, None, None, 15)}, names, False
        )
        hold, cardio = LoggedSet.objects.order_by('position')
        self.assertEqual((hold.seconds, hold.weight_lb, hold.minutes), (40, None, None))
        self.assertEqual((cardio.minutes, cardio.weight_lb, cardio.seconds), (15, None, None))

    def test_finishing_marks_the_session_done_once(self):
        names = {log.position: log.name for log in self.logs()}
        services.save_session(self.session, {(1, 1): (8, None, None, None)}, names, finish=True)
        done_at = WorkoutSession.objects.get(pk=self.session.pk).completed_at
        self.assertIsNotNone(done_at)
        services.save_session(self.session, {}, names, finish=True)
        self.assertEqual(WorkoutSession.objects.get(pk=self.session.pk).completed_at, done_at)

    def test_the_last_weight_is_offered_next_time_for_the_same_exercise(self):
        first = self.logs()[0]
        services.save_session(
            self.session,
            {(1, 1): (8, Decimal('30'), None, None), (1, 2): (8, Decimal('35'), None, None)},
            {1: first.name},
            finish=True,
        )
        next_week = saved_plan(self.user, MONDAY + timedelta(weeks=1))
        later = services.start_session(self.user, next_week, first_training_day(next_week), MONDAY + timedelta(weeks=1))
        log = next((entry for entry in services.session_log(later) if entry.name == first.name), None)
        if log is not None:  # the split rotates week to week, so check only when the exercise comes back
            self.assertEqual(log.last_weight_lb, Decimal('35'))
            self.assertEqual(log.rows[0].weight_lb, Decimal('35'))
        self.assertEqual(services.last_weights_for(self.user, [first.name]), {first.name: Decimal('35')})

    def test_another_users_weights_are_never_offered(self):
        first = self.logs()[0]
        services.save_session(self.session, {(1, 1): (8, Decimal('99'), None, None)}, {1: first.name}, finish=True)
        stranger = onboarded_user(username='stranger', equipment=['dumbbells'], goal='lose_weight')
        self.assertEqual(services.last_weights_for(stranger, [first.name]), {})

    def test_known_exercises_link_to_their_catalog_steps(self):
        WorkoutSession.objects.filter(pk=self.session.pk).update(
            exercises=[
                {'name': 'Goblet Squat', 'sets': 3, 'reps': '8-12'},
                {'name': 'Plank', 'sets': 3, 'reps': '30 sec'},
            ]
        )
        self.session.refresh_from_db()
        goblet, plank = self.logs()
        self.assertEqual(goblet.catalog.source_id, '1760')
        self.assertIsNone(plank.catalog)

    def test_a_malformed_exercise_entry_is_skipped(self):
        WorkoutSession.objects.filter(pk=self.session.pk).update(exercises=['nonsense', {'sets': 3}])
        self.session.refresh_from_db()
        self.assertEqual(self.logs(), [])

    def test_the_database_rejects_a_set_with_two_amounts(self):
        with self.assertRaises(IntegrityError):
            LoggedSet.objects.create(
                session=self.session, position=1, exercise_name='x', set_number=1, reps=5, minutes=5
            )


class HistoryTests(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'])
        self.plan = saved_plan(self.user)
        self.day = first_training_day(self.plan)

    def finish(self, reps=10, weight='20'):
        session = services.start_session(self.user, self.plan, self.day, today=MONDAY)
        name = services.session_log(session)[0].name
        services.save_session(session, {(1, 1): (reps, Decimal(weight), None, None)}, {1: name}, finish=True)
        return session

    def test_weekly_summary_counts_planned_done_and_volume(self):
        self.finish(reps=10, weight='20')
        this_week = services.weekly_summaries(self.user, today=MONDAY + timedelta(days=2))[0]
        self.assertEqual(this_week.week_start, MONDAY)
        self.assertEqual(this_week.planned, services.planned_workouts(self.plan))
        self.assertEqual((this_week.completed, this_week.volume_lb), (1, Decimal('200')))

    def test_unfinished_workouts_are_not_counted(self):
        services.start_session(self.user, self.plan, self.day, today=MONDAY)
        self.assertEqual(services.weekly_summaries(self.user, today=MONDAY)[0].completed, 0)
        self.assertEqual(services.recent_sessions(self.user), [])

    def test_recent_sessions_and_totals_are_the_users_own(self):
        session = self.finish()
        stranger = onboarded_user(username='stranger')
        self.assertEqual(services.recent_sessions(self.user), [session])
        self.assertEqual(services.recent_sessions(stranger), [])
        self.assertEqual(services.session_totals(session), (1, Decimal('200')))

    def test_eight_weeks_newest_first(self):
        weeks = services.weekly_summaries(self.user, today=MONDAY)
        self.assertEqual(len(weeks), 8)
        self.assertEqual(weeks[1].week_start, MONDAY - timedelta(weeks=1))
        self.assertEqual(weeks[1].planned, 0)
