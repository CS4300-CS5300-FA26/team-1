"""The workout split planner (story D-3). Pure: no database, no clock, no randomness.

Given what onboarding learned about the user, it returns the week's training days. The same inputs and seed always
give the same week; a different seed rotates which exercises are chosen ("Generate a new workout plan").

The rules, recorded in ADR-009:
* **Split:** by training days per week. 3 days is full body (A, B, C), 4 is upper/lower twice, 5 is push, pull, legs,
  upper, lower. Days are spread out (Mon/Wed/Fri, Mon/Tue/Thu/Fri, Mon-Fri), so rest days fall between hard ones.
* **Exercises:** only the hand-picked movements in `foundation.POOLS`, from the equipment the user said they have.
  Bodyweight moves fill in where that equipment has no option for a movement. A movement with nothing for the
  user's equipment is left out, and a session that ends up with fewer than `MIN_EXERCISES` is topped up with other
  movements.
* **Rotation:** each time a movement appears in the week, the planner takes the next exercise in its list, so the
  same movement is not repeated at the same slot, and `seed` shifts where the rotation starts.
* **Sets and reps:** from the goal (strength-leaning, fat loss, maintenance, endurance) and experience. Beginners
  never get low-rep heavy work. Fat loss and endurance goals add a cardio finisher.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import foundation as f
from .domain import BODYWEIGHT, TRAINING_DAYS, PlannedDay, PlannedItem, Prescription

MIN_EXERCISES = 4
# When a session is short (for example bodyweight only has no pulldown), these are tried in order.
FILLER_SLOTS = (f.CORE, f.TRICEPS, f.CALVES, f.HINGE, f.SQUAT)

# Which equipment class is tried first when a user has several.
CLASS_ORDER = ('barbell', 'machines', 'dumbbells', 'bands', 'cardio', BODYWEIGHT)

SESSIONS: dict[int, tuple[tuple[str, tuple[str, ...]], ...]] = {
    3: (
        ('Full body A', (f.SQUAT, f.PUSH_HORIZONTAL, f.PULL_HORIZONTAL, f.HINGE, f.CORE)),
        ('Full body B', (f.HINGE, f.PUSH_VERTICAL, f.PULL_VERTICAL, f.SQUAT, f.BICEPS, f.CALVES)),
        ('Full body C', (f.SQUAT, f.PUSH_HORIZONTAL, f.PULL_VERTICAL, f.HINGE, f.TRICEPS, f.CORE)),
    ),
    4: (
        ('Upper body A', (f.PUSH_HORIZONTAL, f.PULL_HORIZONTAL, f.PUSH_VERTICAL, f.PULL_VERTICAL, f.BICEPS, f.TRICEPS)),
        ('Lower body A', (f.SQUAT, f.HINGE, f.CALVES, f.CORE)),
        ('Upper body B', (f.PUSH_VERTICAL, f.PULL_VERTICAL, f.PUSH_HORIZONTAL, f.PULL_HORIZONTAL, f.TRICEPS, f.BICEPS)),
        ('Lower body B', (f.HINGE, f.SQUAT, f.CALVES, f.CORE)),
    ),
    5: (
        ('Push', (f.PUSH_HORIZONTAL, f.PUSH_VERTICAL, f.TRICEPS, f.CORE)),
        ('Pull', (f.PULL_HORIZONTAL, f.PULL_VERTICAL, f.BICEPS, f.CORE)),
        ('Legs', (f.SQUAT, f.HINGE, f.CALVES, f.CORE)),
        ('Upper body', (f.PUSH_HORIZONTAL, f.PULL_HORIZONTAL, f.PUSH_VERTICAL, f.PULL_VERTICAL, f.BICEPS, f.TRICEPS)),
        ('Lower body', (f.HINGE, f.SQUAT, f.CALVES, f.CORE)),
    ),
}

# goal -> (compound reps, accessory reps, compound rest s, accessory rest s, adds cardio)
GOAL_RULES: dict[str, tuple[tuple[int, int], tuple[int, int], int, int, bool]] = {
    'build_muscle': ((6, 10), (10, 15), 120, 75, False),
    'lose_weight': ((10, 15), (12, 15), 60, 45, True),
    'maintain': ((8, 12), (10, 15), 90, 60, False),
    'endurance': ((15, 20), (15, 20), 45, 45, True),
}
BEGINNER_COMPOUND_REPS = (8, 12)
# experience -> (compound sets, accessory sets, cardio minutes)
EXPERIENCE_RULES = {'beginner': (3, 2, 10), 'intermediate': (3, 3, 15), 'advanced': (4, 3, 20)}


@dataclass(frozen=True)
class PlanInputs:
    goal: str
    experience: str
    equipment: tuple[str, ...]
    days: int
    seed: int = 0


def prescribe(slot: str, goal: str, experience: str) -> Prescription:
    """Sets, reps, and rest for one slot. Unknown goals or levels get the middle choice rather than an error."""
    compound_reps, accessory_reps, compound_rest, accessory_rest, _ = GOAL_RULES.get(goal, GOAL_RULES['maintain'])
    compound_sets, accessory_sets, cardio_minutes = EXPERIENCE_RULES.get(experience, EXPERIENCE_RULES['beginner'])
    if slot == f.CARDIO:
        return Prescription(sets=1, minutes=cardio_minutes)
    if slot in f.COMPOUND_SLOTS:
        reps = BEGINNER_COMPOUND_REPS if experience == 'beginner' and compound_reps[0] < 8 else compound_reps
        return Prescription(sets=compound_sets, reps_min=reps[0], reps_max=reps[1], rest_seconds=compound_rest)
    return Prescription(
        sets=accessory_sets, reps_min=accessory_reps[0], reps_max=accessory_reps[1], rest_seconds=accessory_rest
    )


def candidates(slot: str, equipment: Sequence[str]) -> list[str]:
    """Catalog ids for a slot, preferred class first.

    The user's own equipment comes first and is used on its own when it has an option for the slot; bodyweight
    moves fill in only where their equipment has none (core work for a dumbbell user, push-ups with no equipment).
    """
    pools = f.POOLS.get(slot, {})
    ids: list[str] = []
    for equipment_class in CLASS_ORDER:
        if equipment_class in equipment and equipment_class != BODYWEIGHT:
            ids.extend(i for i in pools.get(equipment_class, ()) if i not in ids)
    return ids or list(pools.get(BODYWEIGHT, ()))


def plan_week(inputs: PlanInputs, catalog: Mapping[str, int]) -> list[PlannedDay]:
    """The week's training days. `catalog` maps each usable catalog id to the caller's id for that exercise;
    ids missing from it (inactive or unknown exercises) are skipped."""
    days = inputs.days if inputs.days in SESSIONS else 3
    adds_cardio = GOAL_RULES.get(inputs.goal, GOAL_RULES['maintain'])[4]
    seen: dict[str, int] = {}  # slot -> times used this week, so the rotation moves on
    planned: list[PlannedDay] = []

    def pick(slot: str, used: set[int]) -> PlannedItem | None:
        usable = [i for i in candidates(slot, inputs.equipment) if i in catalog]
        if not usable:
            return None
        start = inputs.seed + seen.get(slot, 0)
        seen[slot] = seen.get(slot, 0) + 1
        for offset in range(len(usable)):
            exercise_id = catalog[usable[(start + offset) % len(usable)]]
            if exercise_id not in used:
                used.add(exercise_id)
                return PlannedItem(exercise_id, slot, prescribe(slot, inputs.goal, inputs.experience))
        return None

    for day, (title, slots) in zip(TRAINING_DAYS[days], SESSIONS[days], strict=True):
        used: set[int] = set()
        items = [item for slot in slots if (item := pick(slot, used))]
        for slot in FILLER_SLOTS:
            if len(items) >= MIN_EXERCISES:
                break
            if (item := pick(slot, used)) is not None:
                items.append(item)
        if adds_cardio and (item := pick(f.CARDIO, used)) is not None:
            items.append(item)
        planned.append(PlannedDay(day=day, title=title, items=tuple(items)))
    return planned
