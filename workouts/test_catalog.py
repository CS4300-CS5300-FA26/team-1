import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .catalog_loader import CATALOG_FILE, CatalogError, equipment_class, load_catalog, read_catalog, slim_catalog
from .foundation import POOLS
from .models import Exercise

UPSTREAM = [
    {
        'id': '0001',
        'name': '  sled 45в° leg press ',
        'category': 'upper legs',
        'body_part': 'upper legs',
        'target': 'quads',
        'equipment': 'sled machine',
        'secondary_muscles': ['glutes'],
        'muscle_group': 'noisy',
        'instructions': {'en': 'Sit. Push.', 'fr': 'Assis.'},
        'instruction_steps': {'en': [' Sit down. ', 'Push.'], 'fr': ['Assis.']},
        'image': 'images/0001-abc.jpg',
        'gif_url': 'videos/0001-abc.gif',
        'media_id': 'abc',
        'created_at': '2026-03-18T12:31:32+00:00',
        'attribution': '© Gym visual — https://gymvisual.com/',
    }
]


def entry(source_id='9001', **overrides):
    data = {
        'id': source_id,
        'name': 'test press',
        'body_part': 'chest',
        'target': 'pectorals',
        'equipment': 'dumbbell',
        'secondary_muscles': ['triceps'],
        'steps': ['Press up.'],
    }
    data.update(overrides)
    return data


class CommittedCatalogTests(TestCase):
    def test_every_exercise_in_the_file_is_loaded_after_migrate(self):
        data = read_catalog()
        self.assertEqual(Exercise.objects.count(), len(data['exercises']))
        self.assertGreater(len(data['exercises']), 1000)

    def test_the_file_carries_no_gym_visual_media(self):
        # The dataset licence excludes the images and videos from MIT; FitPro doesn't use them (ADR-009).
        text = CATALOG_FILE.read_text(encoding='utf-8')
        for forbidden in ('"image"', '"gif_url"', '"media_id"', '"attribution"', 'videos/', 'images/'):
            self.assertNotIn(forbidden, text)

    def test_the_file_keeps_the_licence_notice(self):
        self.assertIn('MIT', read_catalog()['notice'])
        self.assertTrue((CATALOG_FILE.parent / 'LICENSE-exercise-data.txt').exists())

    def test_every_exercise_has_steps_and_an_equipment_class(self):
        for exercise in Exercise.objects.all():
            self.assertTrue(exercise.steps, exercise.source_id)
            self.assertTrue(exercise.equipment_class, exercise.source_id)

    def test_the_planner_pools_only_name_real_active_exercises_of_the_right_equipment(self):
        by_id = {e.source_id: e for e in Exercise.objects.filter(is_active=True)}
        for slot, classes in POOLS.items():
            for equipment, ids in classes.items():
                for source_id in ids:
                    with self.subTest(slot=slot, equipment=equipment, id=source_id):
                        self.assertIn(source_id, by_id)
                        # A treadmill walk is filed under machines upstream but is cardio equipment to the user.
                        if slot != 'cardio':
                            self.assertEqual(by_id[source_id].equipment_class, equipment)


class SlimCatalogTests(TestCase):
    def test_keeps_english_text_and_drops_media_and_other_languages(self):
        slim = slim_catalog(UPSTREAM)['exercises'][0]
        self.assertEqual(
            slim,
            {
                'id': '0001',
                'name': 'sled 45° leg press',
                'body_part': 'upper legs',
                'target': 'quads',
                'equipment': 'sled machine',
                'secondary_muscles': ['glutes'],
                'steps': ['Sit down.', 'Push.'],
            },
        )

    def test_a_malformed_exercise_is_an_error(self):
        with self.assertRaises(CatalogError):
            slim_catalog([{'id': '1', 'name': 'x'}])

    def test_the_build_command_writes_a_sorted_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder, 'exercises.json'), Path(folder, 'out.json')
            second = {**UPSTREAM[0], 'id': '0002'}
            source.write_text(json.dumps([second, UPSTREAM[0]]), encoding='utf-8')
            call_command('build_exercise_catalog', str(source), '--output', str(output), stdout=StringIO())
            written = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual([e['id'] for e in written['exercises']], ['0001', '0002'])

    def test_the_build_command_rejects_a_bad_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, 'exercises.json')
            source.write_text('{"not": "a list"}', encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('build_exercise_catalog', str(source), stdout=StringIO())


class LoadCatalogTests(TestCase):
    def setUp(self):
        Exercise.objects.all().delete()

    def test_loading_twice_changes_nothing(self):
        data = {'exercises': [entry('9001'), entry('9002')]}
        first, second = load_catalog(data), load_catalog(data)
        self.assertEqual((first.exercises, second.exercises, second.deactivated), (2, 2, 0))
        self.assertEqual(Exercise.objects.count(), 2)

    def test_equipment_is_classed_for_onboarding(self):
        self.assertEqual(equipment_class('ez barbell'), 'barbell')
        self.assertEqual(equipment_class('cable'), 'machines')
        self.assertEqual(equipment_class('kettlebell'), 'other')

    def test_changes_update_in_place(self):
        load_catalog({'exercises': [entry('9001')]})
        pk = Exercise.objects.get(source_id='9001').pk
        load_catalog({'exercises': [entry('9001', name='renamed press', equipment='band')]})
        exercise = Exercise.objects.get(source_id='9001')
        self.assertEqual((exercise.pk, exercise.name, exercise.equipment_class), (pk, 'renamed press', 'bands'))

    def test_an_exercise_that_leaves_the_file_is_deactivated_not_deleted(self):
        load_catalog({'exercises': [entry('9001'), entry('9002')]})
        result = load_catalog({'exercises': [entry('9001')]})
        self.assertEqual(result.deactivated, 1)
        self.assertFalse(Exercise.objects.get(source_id='9002').is_active)
        load_catalog({'exercises': [entry('9001'), entry('9002')]})
        self.assertTrue(Exercise.objects.get(source_id='9002').is_active)

    def test_a_bad_row_writes_nothing(self):
        for bad in (
            entry('9002', steps=[]),
            entry('9002', steps=['  ']),
            entry('9002', name=''),
            entry('9002', secondary_muscles='triceps'),
            entry('9001'),
        ):
            with self.subTest(bad=bad), self.assertRaises(CatalogError):
                load_catalog({'exercises': [entry('9001'), bad]})
            self.assertEqual(Exercise.objects.count(), 0)

    def test_a_missing_field_is_named(self):
        broken = entry('9001')
        del broken['target']
        with self.assertRaisesMessage(CatalogError, "missing 'target'"):
            load_catalog({'exercises': [broken]})

    def test_read_catalog_rejects_unreadable_files(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder, 'nope.json')
            with self.assertRaises(CatalogError):
                read_catalog(missing)
            wrong = Path(folder, 'wrong.json')
            wrong.write_text('{"exercises": 3}', encoding='utf-8')
            with self.assertRaises(CatalogError):
                read_catalog(wrong)

    def test_the_load_command_reports_and_fails_loudly(self):
        out = StringIO()
        call_command('load_exercise_catalog', stdout=out)
        self.assertIn('Loaded', out.getvalue())
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder, 'bad.json')
            bad.write_text('nope', encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('load_exercise_catalog', '--file', str(bad), stdout=StringIO())
