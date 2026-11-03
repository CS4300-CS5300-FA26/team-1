import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workouts.catalog_loader import CATALOG_FILE, CatalogError, slim_catalog


class Command(BaseCommand):
    help = (
        'Build workouts/data/exercise_catalog.json from the upstream exercises.json: English text only, '
        'no image or video references (see ADR-009).'
    )

    def add_arguments(self, parser):
        parser.add_argument('source', type=Path, help='The upstream exercises.json.')
        parser.add_argument('--output', type=Path, default=CATALOG_FILE, help='Where to write the catalog.')

    def handle(self, *args, **options):
        try:
            upstream = json.loads(options['source'].read_text(encoding='utf-8'))
            if not isinstance(upstream, list):
                raise CatalogError('The upstream file must be a list of exercises.')
            catalog = slim_catalog(upstream)
        except (OSError, ValueError) as exc:
            raise CommandError(f'Cannot build the catalog: {exc}') from exc
        # Sorted by id so rebuilding from the same upstream gives the same file, and diffs stay readable.
        catalog['exercises'].sort(key=lambda exercise: exercise['id'])
        options['output'].write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'Wrote {len(catalog["exercises"])} exercises to {options["output"]}.'))
