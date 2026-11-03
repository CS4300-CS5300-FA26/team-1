from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase

from core.models import UserProfile

from . import services
from .models import Exercise, LoggedSet, PlannedExercise, PlannedWorkout, WorkoutPlan, WorkoutSession
from .test_helpers import onboarded_user

MONDAY = date(2026, 11, 2)  # a Monday


def profile_of(user: User) -> UserProfile:
    return UserProfile.objects.get(user=user)


class PlanTests(TestCase):
    def setUp(self):
        self.user = onboarded_user()
        self.profile = profile_of(self.user)

    def test_the_first_visit_makes_a_plan_for_the_week_and_later_visits_reuse_it(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY + timedelta(days=3))
        self.assertEqual(plan.week_start, MONDAY)
        again = services.current_plan(self.user, self.profile, today=MONDAY)
        self.assertEqual(plan.pk, again.pk)
        self.assertEqual(WorkoutPlan.objects.count(), 1)

    def test_a_beginner_gets_three_training_days_by_default(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        self.assertEqual(list(plan.workouts.values_list('day', flat=True)), [0, 2, 4])

    def test_each_experience_level_has_its_default_days(self):
        for level, days in (('intermediate', 4), ('advanced', 5)):
            user = onboarded_user(username=level, experience=level)
            plan = services.current_plan(user, profile_of(user), today=MONDAY)
            self.assertEqual(plan.workouts.count(), days)

    def test_the_chosen_training_days_win_and_remake_the_plan(self):
        first = services.current_plan(self.user, self.profile, today=MONDAY)
        services.set_days_per_week(self.user, 5)
        second = services.current_plan(self.user, self.profile, today=MONDAY)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.workouts.count(), 5)
        self.assertEqual(WorkoutPlan.objects.count(), 1)

    def test_unsupported_training_days_are_refused(self):
        with self.assertRaises(ValueError):
            services.set_days_per_week(self.user, 7)

    def test_the_plan_is_remade_when_equipment_changes(self):
        services.current_plan(self.user, self.profile, today=MONDAY)
        self.profile.equipment = ['dumbbells']
        self.profile.save()
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        self.assertEqual(plan.inputs['equipment'], ['dumbbells'])
        classes = set(
            PlannedExercise.objects.filter(workout__plan=plan).values_list('exercise__equipment_class', flat=True)
        )
        self.assertIn('dumbbells', classes)

    def test_a_new_plan_picks_different_exercises(self):
        self.profile.equipment = ['dumbbells', 'bands']
        self.profile.save()

        def names(plan):
            return list(PlannedExercise.objects.filter(workout__plan=plan).values_list('exercise_id', flat=True))

        first = services.current_plan(self.user, self.profile, today=MONDAY)
        first_names = names(first)
        second = services.new_plan(self.user, self.profile, today=MONDAY)
        self.assertNotEqual(first_names, names(second))
        self.assertEqual(WorkoutPlan.objects.count(), 1)

    def test_a_plan_with_a_retired_exercise_is_remade(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        retired = PlannedExercise.objects.filter(workout__plan=plan)[0].exercise
        Exercise.objects.filter(pk=retired.pk).update(is_active=False)
        remade = services.current_plan(self.user, self.profile, today=MONDAY)
        self.assertNotEqual(plan.pk, remade.pk)
        self.assertFalse(PlannedExercise.objects.filter(workout__plan=remade, exercise=retired).exists())

    def test_plans_are_per_user(self):
        other = onboarded_user(username='other')
        services.current_plan(self.user, self.profile, today=MONDAY)
        services.current_plan(other, profile_of(other), today=MONDAY)
        self.assertEqual(WorkoutPlan.objects.filter(user=self.user).count(), 1)
        self.assertEqual(WorkoutPlan.objects.filter(user=other).count(), 1)

    def test_every_planned_exercise_is_an_active_catalog_exercise_in_the_users_equipment(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        for item in PlannedExercise.objects.filter(workout__plan=plan).select_related('exercise'):
            self.assertTrue(item.exercise.is_active)
            self.assertEqual(item.exercise.equipment_class, 'none')

    def test_training_days_for_macro_targets_reads_without_making_a_plan(self):
        self.assertIsNone(services.training_days(self.user, MONDAY))
        self.assertEqual(WorkoutPlan.objects.count(), 0)
        services.current_plan(self.user, self.profile, today=MONDAY)
        self.assertEqual(services.training_days(self.user, MONDAY + timedelta(days=2)), frozenset({0, 2, 4}))

    def test_the_overview_has_seven_days_with_rest_days(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        overview = services.week_overview(plan, today=MONDAY + timedelta(days=2))
        self.assertEqual(
            [d.status for d in overview], ['planned', 'rest', 'planned', 'rest', 'planned', 'rest', 'rest']
        )
        self.assertEqual([d.is_today for d in overview], [False, False, True, False, False, False, False])


class SessionTests(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'])
        self.profile = profile_of(self.user)
        self.plan = services.current_plan(self.user, self.profile, today=MONDAY)
        self.workout = self.plan.workouts.all()[0]

    def test_starting_twice_gives_one_session(self):
        first = services.start_session(self.user, self.workout, today=MONDAY)
        second = services.start_session(self.user, self.workout, today=MONDAY)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual((first.title, first.performed_on, first.user), (self.workout.title, MONDAY, self.user))

    def log(self, session, reps=10, weight='25'):
        entries = {
            (log.planned.exercise_id, 1): (reps, Decimal(weight) if not log.planned.is_timed else None, None)
            for log in services.session_log(session)
            if not log.planned.is_timed
        }
        services.save_session(session, entries, finish=False)

    def test_the_log_has_a_row_per_planned_set(self):
        session = services.start_session(self.user, self.workout, today=MONDAY)
        logs = services.session_log(session)
        self.assertEqual(len(logs), self.workout.exercises.count())
        for log in logs:
            self.assertEqual([row.number for row in log.rows], list(range(1, log.planned.sets + 1)))

    def test_saving_stores_sets_and_clearing_removes_them(self):
        session = services.start_session(self.user, self.workout, today=MONDAY)
        item = self.workout.exercises.all()[0]
        services.save_session(session, {(item.exercise_id, 1): (8, Decimal('30.5'), None)}, finish=False)
        saved = LoggedSet.objects.get(session=session)
        self.assertEqual((saved.reps, saved.weight_lb), (8, Decimal('30.5')))
        services.save_session(session, {(item.exercise_id, 1): (None, Decimal('30'), None)}, finish=False)
        self.assertFalse(LoggedSet.objects.exists())

    def test_saving_again_updates_rather_than_duplicates(self):
        session = services.start_session(self.user, self.workout, today=MONDAY)
        item = self.workout.exercises.all()[0]
        services.save_session(session, {(item.exercise_id, 1): (8, None, None)}, finish=False)
        services.save_session(session, {(item.exercise_id, 1): (9, None, None)}, finish=False)
        self.assertEqual(list(LoggedSet.objects.values_list('reps', flat=True)), [9])

    def test_finishing_marks_it_complete_once(self):
        session = services.start_session(self.user, self.workout, today=MONDAY)
        item = self.workout.exercises.all()[0]
        services.save_session(session, {(item.exercise_id, 1): (8, None, None)}, finish=True)
        session.refresh_from_db()
        stamp = session.completed_at
        self.assertIsNotNone(stamp)
        services.save_session(session, {}, finish=True)
        session.refresh_from_db()
        self.assertEqual(session.completed_at, stamp)

    def test_cardio_is_logged_in_minutes(self):
        self.profile.goal = 'lose_weight'
        self.profile.save()
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        workout = plan.workouts.all()[0]
        session = services.start_session(self.user, workout, today=MONDAY)
        cardio = next(log for log in services.session_log(session) if log.planned.is_timed)
        services.save_session(session, {(cardio.planned.exercise_id, 1): (None, Decimal('20'), 12)}, finish=False)
        saved = LoggedSet.objects.get(session=session)
        self.assertEqual((saved.minutes, saved.reps, saved.weight_lb), (12, None, None))

    def test_weights_start_from_the_last_session_and_only_the_users_own(self):
        first = services.start_session(self.user, self.workout, today=MONDAY)
        self.log(first, weight='40')
        first.completed_at = first.started_at
        first.save()
        second_workout = self.plan.workouts.order_by('day')[1]
        # The same exercise in a later session is prefilled from the heavier earlier one.
        item = self.workout.exercises.all()[0]
        PlannedExercise.objects.filter(workout=second_workout, position=1).update(exercise=item.exercise)
        second = services.start_session(self.user, second_workout, today=MONDAY + timedelta(days=2))
        row = next(log for log in services.session_log(second) if log.planned.exercise_id == item.exercise_id)
        self.assertEqual(row.rows[0].weight_lb, Decimal('40.0'))

        stranger = onboarded_user(username='stranger')
        other_plan = services.current_plan(stranger, profile_of(stranger), today=MONDAY)
        other_workout = other_plan.workouts.all()[0]
        PlannedExercise.objects.filter(workout=other_workout, position=1).update(exercise=item.exercise)
        theirs = services.start_session(stranger, other_workout, today=MONDAY)
        row = next(log for log in services.session_log(theirs) if log.planned.exercise_id == item.exercise_id)
        self.assertIsNone(row.rows[0].weight_lb)

    def test_a_session_outlives_the_plan_it_came_from(self):
        session = services.start_session(self.user, self.workout, today=MONDAY)
        self.log(session)
        services.new_plan(self.user, self.profile, today=MONDAY)
        session.refresh_from_db()
        self.assertIsNone(session.planned_workout)
        self.assertEqual(session.title, self.workout.title)
        self.assertTrue(session.sets.exists())
        self.assertEqual(services.session_log(session), [])
        self.assertEqual(PlannedWorkout.objects.filter(pk=self.workout.pk).count(), 0)


class ProgressTests(TestCase):
    def setUp(self):
        self.user = onboarded_user(equipment=['dumbbells'])
        self.profile = profile_of(self.user)

    def finished_session(self, plan, day_offset, weight, reps=10):
        workout = plan.workouts.order_by('day')[0]
        session = WorkoutSession.objects.create(
            user=self.user,
            planned_workout=None,
            title=workout.title,
            performed_on=plan.week_start + timedelta(days=day_offset),
            completed_at=plan.created_at,
        )
        exercise = workout.exercises.all()[0].exercise
        LoggedSet.objects.create(session=session, exercise=exercise, set_number=1, reps=reps, weight_lb=weight)
        LoggedSet.objects.create(session=session, exercise=exercise, set_number=2, reps=reps, weight_lb=weight)
        return session

    def test_weekly_summaries_count_completed_workouts_and_volume(self):
        this_week = services.current_plan(self.user, self.profile, today=MONDAY)
        last_week = services.current_plan(self.user, self.profile, today=MONDAY - timedelta(days=7))
        self.finished_session(this_week, 0, Decimal('50'))
        self.finished_session(last_week, 1, Decimal('40'))
        self.finished_session(last_week, 2, Decimal('40'), reps=5)
        weeks = services.weekly_summaries(self.user, weeks=3, today=MONDAY)
        self.assertEqual(
            [w.week_start for w in weeks], [MONDAY, MONDAY - timedelta(days=7), MONDAY - timedelta(days=14)]
        )
        self.assertEqual((weeks[0].completed, weeks[0].planned, weeks[0].volume_lb), (1, 3, Decimal('1000')))
        self.assertEqual((weeks[1].completed, weeks[1].volume_lb), (2, Decimal('1200')))
        self.assertEqual((weeks[2].completed, weeks[2].planned, weeks[2].volume_lb), (0, 0, Decimal('0')))

    def test_unfinished_sessions_and_other_users_do_not_count(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        unfinished = self.finished_session(plan, 0, Decimal('50'))
        unfinished.completed_at = None
        unfinished.save()
        stranger = onboarded_user(username='stranger')
        theirs = services.current_plan(stranger, profile_of(stranger), today=MONDAY)
        WorkoutSession.objects.create(user=stranger, title='x', performed_on=MONDAY, completed_at=theirs.created_at)
        mine = services.weekly_summaries(self.user, weeks=1, today=MONDAY)[0]
        self.assertEqual((mine.completed, mine.volume_lb), (0, Decimal('0')))
        self.assertEqual(services.recent_sessions(self.user), [])

    def test_session_totals(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        session = self.finished_session(plan, 0, Decimal('50'))
        self.assertEqual(services.session_totals(session), (2, Decimal('1000')))


class RaceTests(TestCase):
    """Two requests can reach the same code at once; the database constraint decides and the loser reuses the winner."""

    def setUp(self):
        self.user = onboarded_user()
        self.profile = profile_of(self.user)

    def test_losing_the_race_to_make_a_plan_uses_the_existing_one(self):
        plan = services.current_plan(self.user, self.profile, today=MONDAY)
        with mock.patch.object(WorkoutPlan.objects, 'create', side_effect=IntegrityError):
            result = services.new_plan(self.user, self.profile, today=MONDAY)
        self.assertEqual(result.pk, plan.pk)
        self.assertEqual(WorkoutPlan.objects.count(), 1)

    def test_losing_the_race_to_start_a_session_uses_the_existing_one(self):
        workout = services.current_plan(self.user, self.profile, today=MONDAY).workouts.all()[0]
        session = services.start_session(self.user, workout, today=MONDAY)
        with mock.patch.object(WorkoutSession.objects, 'get_or_create', side_effect=IntegrityError):
            result = services.start_session(self.user, workout, today=MONDAY)
        self.assertEqual(result.pk, session.pk)
