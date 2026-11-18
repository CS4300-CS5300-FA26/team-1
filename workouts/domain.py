"""Plain constants and value types for workouts (story D-3 and exercise tracking). No Django imports.

Equipment classes are the keys of `core.models.EQUIPMENT_CHOICES` (what onboarding asks) plus 'other' for catalog
equipment that onboarding can't ask about (kettlebells, stability balls, and so on).
"""

from dataclasses import dataclass

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

BODYWEIGHT = 'none'
OTHER_EQUIPMENT = 'other'

# The catalog's `equipment` value -> the onboarding equipment key a user needs to have for it. Anything not listed
# (kettlebell, stability ball, weighted, ...) is 'other' and is never planned, because onboarding can't say whether
# the user owns it.
EQUIPMENT_CLASS = {
    'body weight': 'none',
    'dumbbell': 'dumbbells',
    'barbell': 'barbell',
    'ez barbell': 'barbell',
    'olympic barbell': 'barbell',
    'trap bar': 'barbell',
    'leverage machine': 'machines',
    'smith machine': 'machines',
    'cable': 'machines',
    'sled machine': 'machines',
    'assisted': 'machines',
    'hammer': 'machines',
    'band': 'bands',
    'resistance band': 'bands',
    'stationary bike': 'cardio',
    'elliptical machine': 'cardio',
    'stepmill machine': 'cardio',
    'skierg machine': 'cardio',
    'upper body ergometer': 'cardio',
}

# Training days per week the planner supports, and what each experience level gets until the user chooses.
DAYS_PER_WEEK_CHOICES = (3, 4, 5)
DEFAULT_DAYS = {'beginner': 3, 'intermediate': 4, 'advanced': 5}
# Which weekdays (0 = Monday) each choice trains on; the rest are rest days.
TRAINING_DAYS = {3: (0, 2, 4), 4: (0, 1, 3, 4), 5: (0, 1, 2, 3, 4)}

# Bounds for logged sets. Wide enough for real lifts, tight enough to catch typos like 5000 reps.
MAX_REPS = 200
MAX_WEIGHT_LB = 2000
MAX_MINUTES = 300


@dataclass(frozen=True)
class Prescription:
    """How many sets of how many reps, and how long to rest, for one exercise. Cardio has `minutes` instead."""

    sets: int = 1
    reps_min: int | None = None
    reps_max: int | None = None
    rest_seconds: int | None = None
    minutes: int | None = None


@dataclass(frozen=True)
class PlannedItem:
    exercise_id: int
    slot: str
    prescription: Prescription


@dataclass(frozen=True)
class PlannedDay:
    day: int
    title: str
    items: tuple[PlannedItem, ...]
