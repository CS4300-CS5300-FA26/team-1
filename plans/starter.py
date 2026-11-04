"""Fixed starter plan shown when the generator is unavailable.

Deliberately static (no calculation, no database), so it still works when the generator fails.
It is a 3-day bodyweight full-body plan with general-purpose macro targets.
"""

from copy import deepcopy

_WORKOUT = [
    {'name': 'Bodyweight Squat', 'sets': 3, 'reps': '10-15'},
    {'name': 'Push-Up', 'sets': 3, 'reps': '8-12'},
    {'name': 'Glute Bridge', 'sets': 3, 'reps': '10-15'},
    {'name': 'Reverse Lunge', 'sets': 3, 'reps': '8-12'},
    {'name': 'Plank', 'sets': 3, 'reps': '30-45 sec'},
]

_STARTER_PLAN = {
    'days': [
        {'day': 'Monday', 'name': 'Starter Full Body', 'exercises': _WORKOUT},
        {'day': 'Tuesday', 'name': 'Rest', 'exercises': []},
        {'day': 'Wednesday', 'name': 'Starter Full Body', 'exercises': _WORKOUT},
        {'day': 'Thursday', 'name': 'Rest', 'exercises': []},
        {'day': 'Friday', 'name': 'Starter Full Body', 'exercises': _WORKOUT},
        {'day': 'Saturday', 'name': 'Rest', 'exercises': []},
        {'day': 'Sunday', 'name': 'Rest', 'exercises': []},
    ],
    'macros': {'calories': 2000, 'protein': 120, 'carbs': 254, 'fat': 56},
}


def starter_plan():
    """Return a fresh copy, so callers can never change the shared constant."""
    return deepcopy(_STARTER_PLAN)
