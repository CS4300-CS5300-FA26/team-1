"""Plain constants and value types for exercise tracking. No Django imports.

The weekly split itself comes from the `plans` app (ADR-012). Its exercises are stored as text, for example
`{'name': 'Goblet Squat', 'sets': 3, 'reps': '8-12'}`, and `parse_target` turns that `reps` text into what a set
is logged in: reps (with an optional weight), seconds held, or minutes of cardio.

Equipment classes are the keys of `core.models.EQUIPMENT_CHOICES` (what onboarding asks) plus 'other' for catalog
equipment that onboarding can't ask about (kettlebells, stability balls, and so on).
"""

import re
from dataclasses import dataclass

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

OTHER_EQUIPMENT = 'other'

# The catalog's `equipment` value -> the onboarding equipment key a user needs to have for it. Anything not listed
# (kettlebell, stability ball, weighted, ...) is 'other'.
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

# Bounds for logged sets. Wide enough for real lifts, tight enough to catch typos like 5000 reps.
MAX_REPS = 200
MAX_WEIGHT_LB = 2000
MAX_SECONDS = 900
MAX_MINUTES = 300

# How a set is logged.
REPS = 'reps'
SECONDS = 'seconds'
MINUTES = 'minutes'

# Suggested rest between sets, for the rest timer. The plans generator doesn't prescribe rest, so this follows the
# usual rule of thumb: heavier sets (12 reps or fewer) get longer rest, lighter sets and holds get less, and cardio
# is done in one go.
REST_SECONDS_HEAVY = 90
REST_SECONDS_LIGHT = 60
REST_SECONDS_HOLD = 45

_RANGE = r'(\d+)(?:\s*-\s*(\d+))?'


@dataclass(frozen=True)
class Target:
    """What one exercise of the plan asks for: `sets` of `low`-`high` reps (or seconds), or `low` minutes."""

    kind: str
    sets: int
    low: int | None = None
    high: int | None = None
    text: str = ''

    @property
    def rest_seconds(self) -> int | None:
        if self.kind == MINUTES or self.sets < 2:
            return None
        if self.kind == SECONDS:
            return REST_SECONDS_HOLD
        return REST_SECONDS_HEAVY if self.high is not None and self.high <= 12 else REST_SECONDS_LIGHT

    def describe(self) -> str:
        if self.kind == MINUTES:
            return f'{self.text} at a steady pace' if self.text else 'Cardio'
        unit = 'seconds' if self.kind == SECONDS else 'reps'
        amount = self.text.replace(' sec', '') if self.text else ''
        sets = f'{self.sets} set{"s" if self.sets != 1 else ""}'
        return f'{sets} of {amount} {unit}' if amount else sets


def parse_target(sets: int, reps: str) -> Target:
    """Read a plan exercise's `sets` and `reps` text ('8-12', '30-45 sec', '20 min').

    Anything else is logged as reps, so a new format in the plan never stops a workout from being logged.
    """
    text = (reps or '').strip()
    sets = max(1, int(sets or 1))
    minutes = re.fullmatch(rf'{_RANGE}\s*min', text)
    if minutes:
        return Target(MINUTES, 1, int(minutes.group(1)), None, text)
    seconds = re.fullmatch(rf'{_RANGE}\s*sec', text)
    if seconds:
        low = int(seconds.group(1))
        return Target(SECONDS, sets, low, int(seconds.group(2) or low), text)
    count = re.fullmatch(_RANGE, text)
    if count:
        low = int(count.group(1))
        return Target(REPS, sets, low, int(count.group(2) or low), text)
    return Target(REPS, sets, None, None, text)
