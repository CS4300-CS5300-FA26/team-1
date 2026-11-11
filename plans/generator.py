"""Rule-based weekly plan generator (no database or Django imports, so it is easy to test).

generate_plan(profile) returns a dict:

    {
      'days': [  # always 7 entries, Monday first
        {'day': 'Monday', 'name': 'Full Body A',
         'exercises': [{'name': 'Goblet Squat', 'sets': 3, 'reps': '8-12'}, ...]},
        {'day': 'Tuesday', 'name': 'Rest', 'exercises': []},
        ...
      ],
      'macros': {'calories': 2400, 'protein': 160, 'carbs': 280, 'fat': 67},
    }

It raises PlanGenerationError if the profile is incomplete or invalid; the caller then
falls back to the starter plan.
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
    'core': [('none', 'Plank')],
    'cardio': [('cardio', 'Treadmill or Bike Intervals'), ('none', 'Brisk Walk or Jog')],
}

# --- Training split ---------------------------------------------------------------------
# Beginners train 3 days, intermediates 4, advanced 5. Weekday numbers: 0 = Monday.
TRAINING_DAYS = {'beginner': 3, 'intermediate': 4, 'advanced': 5}
TRAINING_WEEKDAYS = {3: (0, 2, 4), 4: (0, 1, 3, 4), 5: (0, 1, 2, 3, 4)}

SPLITS = {
    3: [
        ('Full Body A', ['squat', 'push', 'row', 'lunge', 'core']),
        ('Full Body B', ['hinge', 'overhead', 'pulldown', 'core']),
        ('Full Body A', ['squat', 'push', 'row', 'lunge', 'core']),
    ],
    4: [
        ('Upper Body A', ['push', 'row', 'overhead', 'pulldown']),
        ('Lower Body A', ['squat', 'hinge', 'lunge', 'core']),
        ('Upper Body B', ['overhead', 'pulldown', 'push', 'row']),
        ('Lower Body B', ['hinge', 'lunge', 'squat', 'core']),
    ],
    5: [
        ('Upper Body A', ['push', 'row', 'overhead', 'pulldown']),
        ('Lower Body A', ['squat', 'hinge', 'lunge', 'core']),
        ('Upper Body B', ['overhead', 'pulldown', 'push', 'row']),
        ('Lower Body B', ['hinge', 'lunge', 'squat', 'core']),
        ('Full Body', ['squat', 'push', 'row', 'hinge', 'core']),
    ],
}

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


def generate_plan(profile):
    """Build the 7-day plan and daily macro targets for a profile."""
    goal, level, weight, height, age, equipment = _read_profile(profile)

    training_days = TRAINING_DAYS[level]
    sets = 4 if level == 'advanced' else 3
    split = SPLITS[training_days]
    weekdays = TRAINING_WEEKDAYS[training_days]

    days: list[dict[str, Any]] = []
    for index, day_name in enumerate(DAY_NAMES):
        if index not in weekdays:
            days.append({'day': day_name, 'name': 'Rest', 'exercises': []})
            continue
        workout_name, movements = split[weekdays.index(index)]
        exercises = []
        for movement in movements:
            reps = CORE_REPS if movement == 'core' else GOAL_REPS[goal]
            exercises.append({'name': pick_exercise(movement, equipment), 'sets': sets, 'reps': reps})
        if goal in GOAL_CARDIO:
            exercises.append({'name': pick_exercise('cardio', equipment), 'sets': 1, 'reps': GOAL_CARDIO[goal]})
        days.append({'day': day_name, 'name': workout_name, 'exercises': exercises})

    macros = calculate_macros(goal, weight, height, age, training_days)
    return {'days': days, 'macros': macros}
