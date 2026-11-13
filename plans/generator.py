"""Rule-based weekly plan generator (no database or Django imports, so it is easy to test).

generate_plan(profile, split=None, after=None) returns a dict:

    {
      'days': [  # always 7 entries, Monday first
        {'day': 'Monday', 'name': 'Full Body A',
         'exercises': [{'name': 'Goblet Squat', 'sets': 3, 'reps': '8-12'}, ...]},
        {'day': 'Tuesday', 'name': 'Rest', 'exercises': []},
        ...
      ],
      'macros': {'calories': 2400, 'protein': 160, 'carbs': 280, 'fat': 67},
      'split': 'full_body',  # which SPLIT_STYLES entry built the workouts (see ADR-013)
    }

`split` picks a split style. Without it, `after` (last week's style) picks the next style in
rotation, and with neither the default style for the user's experience level is used. The
number of training days never depends on the split, so macro targets don't either.

It raises PlanGenerationError if the profile is incomplete or invalid, or the requested split is
not available; the caller then falls back to the starter plan.
"""

from typing import Any

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

# --- Exercise library -------------------------------------------------------------------
# Each movement lists (required equipment, exercise) in order of preference; the first one the
# user can do wins. The last entry of every movement is bodyweight ('none'), so there is always
# a fallback. Keys match core.models.EQUIPMENT_CHOICES.
EXERCISES = {
    'squat': [
        ('barbell', 'Barbell Back Squat'),
        ('machines', 'Leg Press'),
        ('dumbbells', 'Goblet Squat'),
        ('bands', 'Banded Squat'),
        ('none', 'Bodyweight Squat'),
    ],
    'hinge': [
        ('barbell', 'Romanian Deadlift'),
        ('dumbbells', 'Dumbbell Romanian Deadlift'),
        ('bands', 'Banded Good Morning'),
        ('none', 'Glute Bridge'),
    ],
    'push': [
        ('barbell', 'Barbell Bench Press'),
        ('machines', 'Machine Chest Press'),
        ('dumbbells', 'Dumbbell Bench Press'),
        ('bands', 'Banded Chest Press'),
        ('none', 'Push-Up'),
    ],
    'overhead': [
        ('barbell', 'Barbell Overhead Press'),
        ('machines', 'Machine Shoulder Press'),
        ('dumbbells', 'Dumbbell Shoulder Press'),
        ('bands', 'Banded Overhead Press'),
        ('none', 'Pike Push-Up'),
    ],
    'row': [
        ('barbell', 'Barbell Bent-Over Row'),
        ('machines', 'Seated Cable Row'),
        ('dumbbells', 'One-Arm Dumbbell Row'),
        ('bands', 'Banded Row'),
        ('none', 'Prone Y-T Raise'),
    ],
    'pulldown': [
        ('machines', 'Lat Pulldown'),
        ('bands', 'Banded Lat Pulldown'),
        ('dumbbells', 'Dumbbell Pullover'),
        ('none', 'Superman Hold'),
    ],
    'lunge': [
        ('dumbbells', 'Dumbbell Walking Lunge'),
        ('barbell', 'Barbell Reverse Lunge'),
        ('bands', 'Banded Split Squat'),
        ('none', 'Reverse Lunge'),
    ],
    'triceps': [
        ('barbell', 'Close-Grip Bench Press'),
        ('machines', 'Cable Triceps Pressdown'),
        ('dumbbells', 'Dumbbell Overhead Triceps Extension'),
        ('bands', 'Banded Triceps Pressdown'),
        ('none', 'Diamond Push-Up'),
    ],
    'biceps': [
        ('barbell', 'Barbell Curl'),
        ('machines', 'Cable Biceps Curl'),
        ('dumbbells', 'Dumbbell Curl'),
        ('bands', 'Banded Curl'),
        ('none', 'Towel Isometric Curl'),
    ],
    'core': [('none', 'Plank')],
    'cardio': [('cardio', 'Treadmill or Bike Intervals'), ('none', 'Brisk Walk or Jog')],
}

# --- Training split ---------------------------------------------------------------------
# Beginners train 3 days, intermediates 4, advanced 5. Weekday numbers: 0 = Monday.
TRAINING_DAYS = {'beginner': 3, 'intermediate': 4, 'advanced': 5}
TRAINING_WEEKDAYS = {3: (0, 2, 4), 4: (0, 1, 3, 4), 5: (0, 1, 2, 3, 4)}

UPPER_A = ('Upper Body A', ['push', 'row', 'overhead', 'pulldown'])
LOWER_A = ('Lower Body A', ['squat', 'hinge', 'lunge', 'core'])
UPPER_B = ('Upper Body B', ['overhead', 'pulldown', 'push', 'row'])
LOWER_B = ('Lower Body B', ['hinge', 'lunge', 'squat', 'core'])
PUSH = ('Push', ['push', 'overhead', 'triceps'])
PULL = ('Pull', ['row', 'pulldown', 'biceps'])
LEGS = ('Legs', ['squat', 'hinge', 'lunge', 'core'])
UPPER = ('Upper Body', ['push', 'row', 'overhead', 'pulldown'])  # extra days after push/pull/legs
LOWER = ('Lower Body', ['hinge', 'lunge', 'squat', 'core'])

# Split styles, in rotation order. Each maps a number of training days to that week's workouts.
# Every style that offers a given day count uses the same weekdays, so switching styles never
# changes how many days someone trains (and so never changes their macro targets).
# Full body is only offered at 3 days: with 4 or 5 training days some would fall back to back.
SPLIT_STYLES = {
    'full_body': {
        3: [
            ('Full Body A', ['squat', 'push', 'row', 'lunge', 'core']),
            ('Full Body B', ['hinge', 'overhead', 'pulldown', 'core']),
            ('Full Body A', ['squat', 'push', 'row', 'lunge', 'core']),
        ],
    },
    'upper_lower': {
        3: [UPPER_A, LOWER_A, UPPER_B],
        4: [UPPER_A, LOWER_A, UPPER_B, LOWER_B],
        5: [UPPER_A, LOWER_A, UPPER_B, LOWER_B, ('Full Body', ['squat', 'push', 'row', 'hinge', 'core'])],
    },
    'push_pull_legs': {
        3: [PUSH, PULL, LEGS],
        4: [PUSH, PULL, LEGS, UPPER],
        5: [PUSH, PULL, LEGS, UPPER, LOWER],
    },
}
SPLIT_LABELS = {'full_body': 'Full Body', 'upper_lower': 'Upper / Lower', 'push_pull_legs': 'Push / Pull / Legs'}
# What a profile gets when nothing says otherwise; this is what every plan used before ADR-013.
DEFAULT_SPLIT = {3: 'full_body', 4: 'upper_lower', 5: 'upper_lower'}

# Reps per set by goal. Cardio is added to every training day for these goals.
GOAL_REPS = {
    'lose_weight': '10-15',
    'build_muscle': '8-12',
    'maintain': '8-12',
    'endurance': '15-20',
}
GOAL_CARDIO = {'lose_weight': '20 min', 'endurance': '30 min'}
CORE_REPS = '30-45 sec'

# --- Macro targets ----------------------------------------------------------------------
LB_TO_KG = 0.45359237
IN_TO_CM = 2.54
DEFAULT_AGE = 25  # onboarding does not ask for age yet
SEX_NEUTRAL_OFFSET = -78  # Mifflin-St Jeor uses +5 (male) / -161 (female); onboarding doesn't ask sex
ACTIVITY = {3: 1.375, 4: 1.45, 5: 1.55}  # multiplier on resting calories, by training days
GOAL_CALORIE_ADJUST = {'lose_weight': -500, 'build_muscle': 250, 'maintain': 0, 'endurance': 100}
PROTEIN_G_PER_LB = {'lose_weight': 1.0, 'build_muscle': 0.9, 'maintain': 0.7, 'endurance': 0.7}
FAT_SHARE = 0.25  # share of calories from fat
MIN_CALORIES = 1200
MAX_PROTEIN_SHARE = 0.35  # keeps very heavy users from getting an absurd protein target


class PlanGenerationError(Exception):
    """The profile is incomplete or invalid, so no plan can be generated."""


def pick_exercise(movement, equipment):
    """Return the best exercise for a movement given the user's equipment keys."""
    for required, name in EXERCISES[movement]:
        if required == 'none' or required in equipment:
            return name
    raise PlanGenerationError(f'No exercise available for {movement}')  # pragma: no cover


def available_splits(training_days):
    """Split styles that can be used with this many training days, in rotation order."""
    return [style for style, by_days in SPLIT_STYLES.items() if training_days in by_days]


def next_split(previous, training_days):
    """The style after `previous` in rotation, among those available for `training_days`.

    If `previous` isn't available (or isn't known), the first available style is returned.
    """
    options = available_splits(training_days)
    if previous in options:
        return options[(options.index(previous) + 1) % len(options)]
    return options[0]


def split_of(plan):
    """The split style of a saved plan.

    Plans saved before ADR-013 have no 'split' key; they were built with the default style for
    their number of training days, so that is inferred. Returns None if it can't be worked out.
    """
    split = plan.get('split')
    if split in SPLIT_STYLES:
        return split
    trained = sum(1 for day in plan.get('days', []) if day.get('exercises'))
    return DEFAULT_SPLIT.get(trained)


def calculate_macros(goal, weight_lb, height_in, age, training_days):
    """Daily calories and grams of protein, carbs and fat (Mifflin-St Jeor estimate)."""
    weight_kg = weight_lb * LB_TO_KG
    height_cm = height_in * IN_TO_CM
    resting = 10 * weight_kg + 6.25 * height_cm - 5 * age + SEX_NEUTRAL_OFFSET
    calories = resting * ACTIVITY[training_days] + GOAL_CALORIE_ADJUST[goal]
    calories = max(MIN_CALORIES, round(calories / 5) * 5)

    protein = min(round(weight_lb * PROTEIN_G_PER_LB[goal]), round(calories * MAX_PROTEIN_SHARE / 4))
    fat = round(calories * FAT_SHARE / 9)
    carbs = max(0, round((calories - protein * 4 - fat * 9) / 4))
    return {'calories': calories, 'protein': protein, 'carbs': carbs, 'fat': fat}


def _read_profile(profile):
    """Pull the fields we need out of a UserProfile and validate them."""
    goal = getattr(profile, 'goal', '')
    level = getattr(profile, 'experience_level', '')
    weight = getattr(profile, 'weight', None)
    height = getattr(profile, 'height_inches', None)
    age = getattr(profile, 'age', None) or DEFAULT_AGE
    equipment = set(getattr(profile, 'equipment', None) or [])

    if goal not in GOAL_REPS:
        raise PlanGenerationError(f'Unknown or missing goal: {goal!r}')
    if level not in TRAINING_DAYS:
        raise PlanGenerationError(f'Unknown or missing experience level: {level!r}')
    if not weight or not height:
        raise PlanGenerationError('Weight and height are required')
    return goal, level, float(weight), float(height), age, equipment


def generate_plan(profile, split=None, after=None):
    """Build the 7-day plan and daily macro targets for a profile.

    `split` chooses the split style; otherwise `after` (the previous week's style) chooses the
    next one in rotation; with neither, the default style for the profile's level is used.
    """
    goal, level, weight, height, age, equipment = _read_profile(profile)

    training_days = TRAINING_DAYS[level]
    sets = 4 if level == 'advanced' else 3
    if split is None:
        split = next_split(after, training_days) if after else DEFAULT_SPLIT[training_days]
    if split not in available_splits(training_days):
        raise PlanGenerationError(f'Split {split!r} is not available for {training_days} training days')
    workouts = SPLIT_STYLES[split][training_days]
    weekdays = TRAINING_WEEKDAYS[training_days]

    days: list[dict[str, Any]] = []
    for index, day_name in enumerate(DAY_NAMES):
        if index not in weekdays:
            days.append({'day': day_name, 'name': 'Rest', 'exercises': []})
            continue
        workout_name, movements = workouts[weekdays.index(index)]
        exercises = []
        for movement in movements:
            reps = CORE_REPS if movement == 'core' else GOAL_REPS[goal]
            exercises.append({'name': pick_exercise(movement, equipment), 'sets': sets, 'reps': reps})
        if goal in GOAL_CARDIO:
            exercises.append({'name': pick_exercise('cardio', equipment), 'sets': 1, 'reps': GOAL_CARDIO[goal]})
        days.append({'day': day_name, 'name': workout_name, 'exercises': exercises})

    macros = calculate_macros(goal, weight, height, age, training_days)
    return {'days': days, 'macros': macros, 'split': split}
