"""FitPro's exercise catalog (data/exercise_catalog.json): building it from the upstream dataset and loading it.

`slim_catalog` turns the upstream `exercises.json` into the file we keep in the repository: English text only, and
none of the Gym visual images or videos, which the dataset's licence excludes from its MIT grant (ADR-009).

`load_catalog` runs after every `migrate` (see `WorkoutsConfig.ready`) and from `manage.py load_exercise_catalog`.
It is idempotent: exercises are matched by `source_id` and updated in place, and ones no longer in the file are
marked inactive rather than deleted, because logged sets point at them. Every row is validated with the model's own
validators before anything is written, in one transaction, so a bad file changes nothing and fails loudly.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from .domain import EQUIPMENT_CLASS, OTHER_EQUIPMENT
from .models import Exercise

CATALOG_FILE = Path(__file__).resolve().parent / 'data' / 'exercise_catalog.json'

EXERCISE_FIELDS = ('name', 'body_part', 'target', 'equipment', 'secondary_muscles', 'steps')

# The dataset's copyright holder asks that the MIT notice travel with the data (data/LICENSE-exercise-data.txt).
SOURCE_NOTICE = (
    'Exercise names, muscles and instruction text: MIT License, Copyright (c) 2026 Hasan Emir Yıldırım. '
    'See LICENSE-exercise-data.txt. Gym visual images and videos are not included and are not covered by that licence.'
)


class CatalogError(ValueError):
    """The catalog file is unreadable or has an invalid entry. Nothing was written."""


@dataclass(frozen=True)
class LoadResult:
    exercises: int
    deactivated: int


def slim_catalog(upstream: list[dict[str, Any]]) -> dict[str, Any]:
    """The upstream dataset as FitPro's catalog: English steps, no media, no ten-language copies of the text."""
    exercises = []
    for raw in upstream:
        try:
            exercises.append(
                {
                    'id': raw['id'],
                    # A few upstream names have a mis-encoded degree sign ("45в°").
                    'name': raw['name'].replace('в°', '°').strip(),
                    'body_part': raw['body_part'],
                    'target': raw['target'],
                    'equipment': raw['equipment'],
                    'secondary_muscles': list(raw.get('secondary_muscles') or []),
                    'steps': [step.strip() for step in raw['instruction_steps']['en']],
                }
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise CatalogError(
                f'Exercise {raw.get("id") if isinstance(raw, dict) else raw!r} is malformed: {exc!r}'
            ) from exc
    return {'notice': SOURCE_NOTICE, 'exercises': exercises}


def read_catalog(path: Path = CATALOG_FILE) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CatalogError(f'Cannot read {path.name}: {exc}') from exc
    if not (isinstance(data, dict) and isinstance(data.get('exercises'), list)):
        raise CatalogError(f'{path.name} needs an "exercises" list.')
    return data


def equipment_class(equipment: str) -> str:
    return EQUIPMENT_CLASS.get(equipment, OTHER_EQUIPMENT)


@transaction.atomic
def load_catalog(data: dict) -> LoadResult:
    existing = {exercise.source_id: exercise for exercise in Exercise.objects.all()}
    seen: set[str] = set()
    to_create: list[Exercise] = []
    to_update: list[Exercise] = []
    for raw in data['exercises']:
        source_id = _field(raw, 'id', 'An exercise')
        if source_id in seen:
            raise CatalogError(f'Exercise {source_id!r} appears twice.')
        seen.add(source_id)
        where = f'Exercise {source_id!r}'
        exercise = existing.get(source_id) or Exercise(source_id=source_id)
        for name in EXERCISE_FIELDS:
            setattr(exercise, name, _field(raw, name, where))
        exercise.equipment_class = equipment_class(exercise.equipment)
        exercise.is_active = True
        _validate(exercise, where)
        (to_update if exercise.pk else to_create).append(exercise)

    Exercise.objects.bulk_create(to_create, batch_size=500)
    Exercise.objects.bulk_update(to_update, [*EXERCISE_FIELDS, 'equipment_class', 'is_active'], batch_size=500)
    deactivated = Exercise.objects.filter(is_active=True).exclude(source_id__in=seen).update(is_active=False)
    return LoadResult(exercises=len(seen), deactivated=deactivated)


def _field(raw: Any, name: str, where: str) -> Any:
    try:
        return raw[name]
    except (KeyError, TypeError) as exc:
        raise CatalogError(f'{where} is missing {name!r}.') from exc


def _validate(exercise: Exercise, where: str) -> None:
    try:
        exercise.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        raise CatalogError(f'{where} is invalid: {exc.message_dict}') from exc
    steps = exercise.steps
    if not (isinstance(steps, list) and steps and all(isinstance(s, str) and s.strip() for s in steps)):
        raise CatalogError(f'{where} needs a list of non-empty steps.')
    muscles = exercise.secondary_muscles
    if not (isinstance(muscles, list) and all(isinstance(m, str) for m in muscles)):
        raise CatalogError(f'{where} needs secondary_muscles as a list of text.')
