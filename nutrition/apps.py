from django.apps import AppConfig
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models.signals import post_migrate


def load_catalog_after_migrate(sender, using=DEFAULT_DB_ALIAS, verbosity=1, **kwargs):
    """Keep the recipe catalog in step with data/recipe_catalog.json whenever the database is migrated.

    The same pattern Django's contenttypes and auth apps use to create their rows. Skipped when the nutrition
    tables don't exist (for example after `migrate nutrition zero`).
    """
    from .catalog_loader import load_catalog, read_catalog
    from .models import Ingredient

    if using != DEFAULT_DB_ALIAS:
        return
    if Ingredient._meta.db_table not in connections[using].introspection.table_names():
        return
    result = load_catalog(read_catalog())
    if verbosity >= 2:
        print(f'Loaded recipe catalog: {result.recipes} recipes, {result.ingredients} ingredients.')  # noqa: T201


class NutritionConfig(AppConfig):
    name = 'nutrition'

    def ready(self):
        post_migrate.connect(load_catalog_after_migrate, sender=self)
