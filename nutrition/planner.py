"""Build a week of budget meals from a list of recipes (pure logic, no I/O; see ADR-008).

Rules:
* The plan covers the meals the user chose (breakfast, lunch, dinner, or a subset), one serving each.
  Breakfasts come from breakfast recipes; lunches and dinners come from mains.
* Every meal in the week is a different recipe, so users see the widest choice. Only if a course has
  too few recipes to fill the week are recipes repeated, and then as evenly as possible.
* A day's macro targets are split across its meals by MEAL_WEIGHTS (renormalised for the meals chosen).
* If even the lowest-cost week is over budget, that week is returned and the plan reports how far over
  it is. Otherwise, with macro targets, each meal gets the recipe that best fits its share of the day
  while the rest of the week can still be bought within budget. Without targets, the lowest-cost week
  is used.
"""

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from math import ceil

from .domain import COURSE_FOR_MEAL, COURSES, MEALS, MacroTargets, MealPlan, PlannedDay, PlannedMeal, Recipe, money

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

# How a day's macros are shared between meals; renormalised over the meals actually planned.
MEAL_WEIGHTS = {'breakfast': 25, 'lunch': 35, 'dinner': 40}

# Protein counts double when scoring fit: it's the macro this audience is usually short of.
FIT_WEIGHTS = {'protein_g': 2.0, 'carbs_g': 1.0, 'fat_g': 1.0}


class NoRecipesError(ValueError):
    """There are no recipes for a meal the plan has to cover."""


def meal_shares(meals: Sequence[str]) -> dict[str, float]:
    """Each planned meal's fraction of the day's macros."""
    total = sum(MEAL_WEIGHTS[meal] for meal in meals)
    return {meal: MEAL_WEIGHTS[meal] / total for meal in meals}


def build_week_plan(
    recipes: Sequence[Recipe],
    budget: Decimal,
    meals: Sequence[str] = MEALS,
    targets: Sequence[MacroTargets] | None = None,
) -> MealPlan:
    """Return the week's plan for `budget` (dollars), covering `meals` each day and fitting `targets` if given."""
    budget = money(budget)
    if budget < 0:
        raise ValueError('Budget cannot be negative.')
    meals = tuple(meal for meal in MEALS if meal in meals)  # known meals only, in day order
    if not meals:
        raise ValueError('A plan needs at least one meal a day.')
    if targets is not None and len(targets) != len(DAY_NAMES):
        raise ValueError(f'Expected {len(DAY_NAMES)} daily targets, got {len(targets)}.')

    slots = [(day, meal) for day in range(len(DAY_NAMES)) for meal in meals]
    shares = meal_shares(meals)
    week = _Week(recipes, slots)
    lowest_cost = week.lowest_cost_assignment()
    if targets is None or week.cost_of(lowest_cost.values()) > budget:
        chosen = lowest_cost
    else:
        meal_targets = {(day, meal): targets[day].share(shares[meal]) for day, meal in slots}
        chosen = week.best_fit_assignment(meal_targets, budget)

    return MealPlan(
        days=tuple(
            PlannedDay(
                day_name=name,
                meals=tuple(
                    PlannedMeal(
                        meal=meal,
                        recipe=chosen[(day, meal)],
                        targets=targets[day].share(shares[meal]) if targets is not None else None,
                    )
                    for meal in meals
                ),
                targets=targets[day] if targets is not None else None,
            )
            for day, name in enumerate(DAY_NAMES)
        ),
        budget=budget,
    )


class _Week:
    """Recipe pools per course and the costing rules shared by both ways of filling the week."""

    def __init__(self, recipes: Sequence[Recipe], slots: Sequence[tuple[int, str]]):
        self.slots = slots
        self.needed = Counter(COURSE_FOR_MEAL[meal] for _, meal in slots)
        unique = {recipe.id: recipe for recipe in recipes}
        # Cheapest first; ties broken by title and id so the same input always gives the same plan.
        self.pools = {
            course: sorted(
                (r for r in unique.values() if r.course == course),
                key=lambda r: (r.cost_per_serving, r.title, r.id),
            )
            for course in COURSES
        }
        self.cap = {}
        for course, needed in self.needed.items():
            pool = self.pools[course]
            if not pool:
                raise NoRecipesError(f'No {course} recipes to plan with.')
            # 1 means every meal is different; it only rises when the pool can't fill the week.
            self.cap[course] = ceil(needed / len(pool))

    def cost_of(self, chosen) -> Decimal:
        return sum((money(r.cost_per_serving) for r in chosen), Decimal(0))

    def cheapest_fill(self, course: str, count: int, used: Counter) -> list[Recipe]:
        """The lowest-cost recipes for `count` more meals of `course`, given what's already used."""
        fill: list[Recipe] = []
        for recipe in self.pools[course]:
            take = min(self.cap[course] - used[recipe.id], count - len(fill))
            fill.extend([recipe] * max(take, 0))
            if len(fill) == count:
                break
        return fill

    def lowest_cost_assignment(self) -> dict[tuple[int, str], Recipe]:
        """Cheapest recipes per course, handed out in day order (Monday gets the cheapest)."""
        queues = {course: self.cheapest_fill(course, count, Counter()) for course, count in self.needed.items()}
        return {slot: queues[COURSE_FOR_MEAL[slot[1]]].pop(0) for slot in self.slots}

    def best_fit_assignment(
        self, meal_targets: dict[tuple[int, str], MacroTargets], budget: Decimal
    ) -> dict[tuple[int, str], Recipe]:
        """Meal by meal, the best-fitting recipe that still leaves the rest of the week affordable.

        A choice is allowed only if every remaining meal can still be filled at the lowest possible
        cost within budget. The caller has checked that the lowest-cost week fits, so at every step at
        least one recipe qualifies (the next one in that lowest-cost week) and the week never goes over
        budget.
        """
        chosen: dict[tuple[int, str], Recipe] = {}
        used: Counter = Counter()
        remaining = Counter(self.needed)
        spent = Decimal(0)
        for slot in self.slots:
            course = COURSE_FOR_MEAL[slot[1]]
            remaining[course] -= 1
            best_key, best = None, None
            for recipe in self.pools[course]:
                if used[recipe.id] >= self.cap[course]:
                    continue
                used[recipe.id] += 1
                rest = sum(
                    (self.cost_of(self.cheapest_fill(c, n, used)) for c, n in remaining.items() if n),
                    Decimal(0),
                )
                used[recipe.id] -= 1
                if spent + money(recipe.cost_per_serving) + rest > budget:
                    continue
                key = (_fit_error(recipe, meal_targets[slot]), recipe.cost_per_serving, recipe.title, recipe.id)
                if best_key is None or key < best_key:
                    best_key, best = key, recipe
            assert best is not None  # noqa: S101 - guaranteed by the affordability invariant above
            chosen[slot] = best
            used[best.id] += 1
            spent += money(best.cost_per_serving)
        return chosen


def _fit_error(recipe: Recipe, targets: MacroTargets) -> float:
    """Weighted relative distance between one serving's macros and a meal's targets (0 is a perfect match)."""
    error = 0.0
    for field, weight in FIT_WEIGHTS.items():
        target = getattr(targets, field)
        error += weight * abs(getattr(recipe, field) - target) / max(target, 1)
    return error
