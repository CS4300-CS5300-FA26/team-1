from django.test import SimpleTestCase

from .domain import TRAINING_DAYS, Prescription
from .foundation import CARDIO, POOLS
from .planner import MIN_EXERCISES, PlanInputs, candidates, plan_week, prescribe

# Every pooled id, mapped to itself, and the equipment class each is listed under.
CATALOG = {source_id: int(source_id) for classes in POOLS.values() for ids in classes.values() for source_id in ids}
CLASS_OF = {
    int(i): cls for slot, classes in POOLS.items() if slot != CARDIO for cls, ids in classes.items() for i in ids
}


def week(goal='build_muscle', experience='beginner', equipment=('none',), days=3, seed=0):
    return plan_week(PlanInputs(goal, experience, equipment, days, seed), CATALOG)


class SplitTests(SimpleTestCase):
    def test_each_choice_trains_on_its_own_days(self):
        for days, weekdays in TRAINING_DAYS.items():
            with self.subTest(days=days):
                self.assertEqual([d.day for d in week(days=days)], list(weekdays))

    def test_the_same_inputs_give_the_same_week(self):
        self.assertEqual(week(seed=4), week(seed=4))

    def test_a_different_seed_rotates_the_exercises(self):
        self.assertNotEqual(week(equipment=('dumbbells',), seed=0), week(equipment=('dumbbells',), seed=1))

    def test_an_unsupported_day_count_falls_back_to_three(self):
        self.assertEqual(len(week(days=9)), 3)

    def test_every_session_has_enough_exercises_for_every_equipment_choice(self):
        for equipment in (('none',), ('dumbbells',), ('barbell',), ('machines',), ('bands',), ('cardio',)):
            for days in TRAINING_DAYS:
                for day in week(equipment=equipment, days=days):
                    with self.subTest(equipment=equipment, days=days, title=day.title):
                        self.assertGreaterEqual(len(day.items), MIN_EXERCISES)

    def test_no_exercise_repeats_within_a_session(self):
        for seed in range(6):
            for day in week(equipment=('dumbbells', 'bands', 'barbell'), days=5, seed=seed):
                ids = [item.exercise_id for item in day.items]
                self.assertEqual(len(ids), len(set(ids)), day.title)

    def test_the_same_slot_rotates_across_the_week(self):
        squats = [
            item.exercise_id for day in week(equipment=('dumbbells',)) for item in day.items if item.slot == 'squat'
        ]
        self.assertEqual(len(squats), len(set(squats)))


class EquipmentTests(SimpleTestCase):
    def test_no_equipment_means_bodyweight_only(self):
        for day in week(equipment=('none',), days=5):
            for item in day.items:
                if item.slot != CARDIO:
                    self.assertEqual(CLASS_OF[item.exercise_id], 'none')

    def test_only_owned_equipment_or_bodyweight_is_planned(self):
        for equipment in (('dumbbells',), ('bands',), ('dumbbells', 'barbell'), ('machines', 'bands')):
            for day in week(equipment=equipment, days=4):
                for item in day.items:
                    if item.slot != CARDIO:
                        self.assertIn(CLASS_OF[item.exercise_id], {'none', *equipment})

    def test_a_slot_with_nothing_for_the_equipment_is_left_out(self):
        for day in week(equipment=('dumbbells',), days=4):
            self.assertNotIn('pull_vertical', [item.slot for item in day.items])

    def test_ids_missing_from_the_catalog_are_skipped(self):
        without = {k: v for k, v in CATALOG.items() if k != '2368'}
        for day in plan_week(PlanInputs('maintain', 'beginner', ('none',), 3), without):
            self.assertNotIn(2368, [item.exercise_id for item in day.items])

    def test_owned_equipment_is_used_instead_of_bodyweight_where_it_has_an_option(self):
        for day in week(equipment=('dumbbells',), days=5, seed=7):
            for item in day.items:
                if item.slot in ('squat', 'push_horizontal', 'push_vertical', 'pull_horizontal', 'biceps', 'triceps'):
                    self.assertEqual(CLASS_OF[item.exercise_id], 'dumbbells', item.slot)

    def test_bodyweight_fills_in_where_owned_equipment_has_no_option(self):
        core = [item for day in week(equipment=('dumbbells',), days=5) for item in day.items if item.slot == 'core']
        self.assertTrue(core)
        self.assertEqual({CLASS_OF[item.exercise_id] for item in core}, {'none'})

    def test_candidates_put_the_preferred_class_first_without_duplicates(self):
        ids = candidates('squat', ('dumbbells', 'barbell'))
        self.assertEqual(ids[0], POOLS['squat']['barbell'][0])
        self.assertEqual(len(ids), len(set(ids)))


class PrescriptionTests(SimpleTestCase):
    def test_beginners_never_get_low_rep_work(self):
        for goal in ('build_muscle', 'lose_weight', 'maintain', 'endurance'):
            self.assertGreaterEqual(prescribe('squat', goal, 'beginner').reps_min or 0, 8)

    def test_more_experience_means_more_compound_sets(self):
        sets = [prescribe('squat', 'maintain', level).sets for level in ('beginner', 'intermediate', 'advanced')]
        self.assertEqual(sets, [3, 3, 4])

    def test_accessory_work_has_higher_reps_and_less_rest(self):
        compound, accessory = (
            prescribe('squat', 'build_muscle', 'advanced'),
            prescribe('biceps', 'build_muscle', 'advanced'),
        )
        self.assertGreater(accessory.reps_min or 0, compound.reps_min or 0)
        self.assertLess(accessory.rest_seconds or 0, compound.rest_seconds or 0)

    def test_cardio_is_timed_and_has_no_reps(self):
        self.assertEqual(prescribe(CARDIO, 'lose_weight', 'intermediate'), Prescription(sets=1, minutes=15))

    def test_fat_loss_and_endurance_end_each_session_with_cardio(self):
        for goal in ('lose_weight', 'endurance'):
            for day in week(goal=goal):
                self.assertEqual(day.items[-1].slot, CARDIO)

    def test_strength_and_maintenance_goals_have_no_cardio_finisher(self):
        for goal in ('build_muscle', 'maintain'):
            for day in week(goal=goal):
                self.assertNotIn(CARDIO, [item.slot for item in day.items])

    def test_unknown_goal_and_level_get_sensible_defaults(self):
        self.assertEqual(prescribe('squat', 'mystery', 'wizard'), prescribe('squat', 'maintain', 'beginner'))
