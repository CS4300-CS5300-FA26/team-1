from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from nutrition.catalog_loader import CATALOG_FILE, CatalogError, load_catalog, read_catalog


class Command(BaseCommand):
    help = 'Load the recipe catalog from a JSON file (default: nutrition/data/recipe_catalog.json).'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=Path, default=CATALOG_FILE, help='Catalog JSON file to load.')

    def handle(self, *args, **options):
        try:
            result = load_catalog(read_catalog(options['file']))
        except CatalogError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f'Loaded {result.recipes} recipes and {result.ingredients} ingredients '
                f'(removed {result.removed_recipes} recipes and {result.removed_ingredients} ingredients '
                'no longer listed).'
            )
        )
