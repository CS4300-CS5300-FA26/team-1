from django.apps import AppConfig
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models.signals import post_migrate


def load_catalog_after_migrate(sender, using=DEFAULT_DB_ALIAS, verbosity=1, **kwargs):
    """Keep the exercise catalog in step with data/exercise_catalog.json whenever the database is migrated.

    The same pattern as the recipe catalog (ADR-008). Skipped when the workouts tables don't exist (for example after
    `migrate workouts zero`).
    """
    from .catalog_loader import load_catalog, read_catalog
    from .models import Exercise

    if using != DEFAULT_DB_ALIAS:
        return
    if Exercise._meta.db_table not in connections[using].introspection.table_names():
        return
    result = load_catalog(read_catalog())
    if verbosity >= 2:
        print(f'Loaded exercise catalog: {result.exercises} exercises.')  # noqa: T201


class WorkoutsConfig(AppConfig):
    name = 'workouts'

    def ready(self):
        post_migrate.connect(load_catalog_after_migrate, sender=self)
