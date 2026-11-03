from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workouts.catalog_loader import CATALOG_FILE, CatalogError, load_catalog, read_catalog


class Command(BaseCommand):
    help = 'Load the exercise catalog from a JSON file (default: workouts/data/exercise_catalog.json).'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=Path, default=CATALOG_FILE, help='Catalog JSON file to load.')

    def handle(self, *args, **options):
        try:
            result = load_catalog(read_catalog(options['file']))
        except CatalogError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f'Loaded {result.exercises} exercises ({result.deactivated} no longer listed, marked inactive).'
            )
        )
