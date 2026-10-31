"""Building a week of meals from recipes, daily macro targets, and (optionally) prices and a budget.

Pure logic with no I/O; see ADR-008. The rules:

* Each planned meal gets one recipe at a portion of 1, 1.5, or 2 servings, so days can actually reach their
  targets. Breakfasts come from breakfast recipes; lunches and dinners from mains.
* Variety: a recipe is used at most twice a week (cook once, eat twice), never twice in one day. The limits
  loosen only if there are too few recipes to fill the week.
* Each day's macros should be as close as possible to that day's targets, scaled to the meals planned (each of
  breakfast, lunch, and dinner covers a third of the day). Closeness is the sum of the relative misses on
  protein, carbohydrate, and fat.
* With prices, the week is costed the way it would be bought: every ingredient is rounded up to whole
  packages. Meals that share ingredients therefore cost less than meals that each need their own, and the
  search finds those overlaps on its own.
* With a budget, staying within it comes first. If no plan the search finds fits, the cheapest plan it finds
  is returned and the caller reports how far over it is. While over budget, plans that use less food (by weight
  times price) are preferred next, which walks the search down to the next whole-package saving instead of
  stalling just above it.
* When generating a new plan, recipes from the plan being replaced are avoided where that costs nothing more.

Search: from a seeded random start, repeatedly swap a single meal (recipe and portion) for the option that most
improves the plan, or swap a recipe for another everywhere it's used, until nothing improves; this is restarted a
few times and the best result kept. It is deterministic for a given seed. It finds very good plans quickly but,
like any local search, doesn't prove the plan is the best possible.
"""

import random
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from math import ceil

from .domain import (
    COURSE_FOR_MEAL,
    DAY_NAMES,
    MEALS,
    MacroTargets,
    PlannedMeal,
    PriceEstimate,
    Recipe,
    WeekPlan,
    purchase_cost,
)

PORTIONS = (Decimal('1'), Decimal('1.5'), Decimal('2'))
MAX_REPEATS = 2
RESTARTS = 6
MAX_PASSES = 40


class NoRecipesError(ValueError):
    """There are no recipes for a meal the plan has to cover."""


@dataclass(frozen=True)
class PlanResult:
    plan: WeekPlan
    cost: Decimal | None  # whole-package cost, when prices were given
    budget: Decimal | None

    @property
    def over_budget_by(self) -> Decimal | None:
        if self.cost is None or self.budget is None:
            return None
        return max(self.cost - self.budget, Decimal('0.00'))


def recipes_with_prices(recipes: Sequence[Recipe], prices: dict[str, PriceEstimate]) -> list[Recipe]:
    """The recipes whose every weighed ingredient has a price."""
    return [r for r in recipes if all(key in prices for key in r.grams_by_ingredient())]


def covers_meals(recipes: Sequence[Recipe], meals: Sequence[str]) -> bool:
    courses = {r.course for r in recipes}
    return all(COURSE_FOR_MEAL[meal] in courses for meal in meals)


def build_week_plan(
    recipes: Sequence[Recipe],
    meals: Sequence[str],
    daily_targets: Sequence[MacroTargets],
    *,
    prices: dict[str, PriceEstimate] | None = None,
    budget: Decimal | None = None,
    seed: int = 0,
    avoid: Collection[str] = frozenset(),
    portions: Sequence[Decimal] = PORTIONS,
    max_repeats: int = MAX_REPEATS,
) -> PlanResult:
    """Plan the week. With `prices`, only fully priced recipes are used and the plan is costed in whole packages.

    `budget` (dollars) only applies together with `prices`.
    """
    meals = tuple(m for m in MEALS if m in meals)
    if not meals:
        raise ValueError('A plan needs at least one meal a day.')
    if len(daily_targets) != len(DAY_NAMES):
        raise ValueError(f'Expected {len(DAY_NAMES)} daily targets, got {len(daily_targets)}.')
    if prices is not None:
        recipes = recipes_with_prices(recipes, prices)
    budget = budget if prices is not None else None
    search = _Search(recipes, meals, daily_targets, prices, budget, avoid, portions, max_repeats)
    # A seeded generator so the same seed gives the same plan; it chooses meals, not anything security-related.
    runs = (search.run(random.Random(seed * 7919 + restart)) for restart in range(RESTARTS))  # noqa: S311  # nosec B311
    best = min(runs, key=lambda r: r[0])
    planned = tuple(
        PlannedMeal(day=day, meal=meal, recipe=recipe, servings=portion)
        for (day, meal), (recipe, portion) in zip(search.slots, best[1], strict=True)
    )
    plan = WeekPlan(meals=planned, daily_targets=tuple(daily_targets), meal_keys=meals)
    cost = purchase_cost(plan.grams_needed(), prices) if prices is not None else None
    return PlanResult(plan=plan, cost=cost, budget=budget)


class _Search:
    """The local search. Grams, macros, and prices are floats here for speed; the final cost uses Decimal."""

    def __init__(self, recipes, meals, daily_targets, prices, budget, avoid, portions, max_repeats):
        self.slots = [(day, meal) for day in range(len(DAY_NAMES)) for meal in meals]
        coverage = len(meals) / len(MEALS)
        self.targets = [(t.protein_g * coverage, t.carbs_g * coverage, t.fat_g * coverage) for t in daily_targets]
        self.budget = float(budget) if budget is not None else None
        self.avoid = frozenset(avoid)
        # Same input, same order: recipes sorted by id so ties always break the same way.
        self.pools: dict[str, list[Recipe]] = {}
        for recipe in sorted({r.id: r for r in recipes}.values(), key=lambda r: r.id):
            self.pools.setdefault(recipe.course, []).append(recipe)
        self.options: dict[str, list[tuple[Recipe, Decimal]]] = {}
        self.cap: dict[str, int] = {}
        self.unique_per_day: dict[str, bool] = {}
        needed = Counter(COURSE_FOR_MEAL[meal] for _, meal in self.slots)
        per_day = Counter(COURSE_FOR_MEAL[meal] for meal in meals)
        for course, count in needed.items():
            pool = self.pools.get(course, [])
            if not pool:
                raise NoRecipesError(f'No {course} recipes to plan with.')
            self.options[course] = [(recipe, portion) for recipe in pool for portion in portions]
            self.cap[course] = max(max_repeats, ceil(count / len(pool)))
            self.unique_per_day[course] = len(pool) >= per_day[course]
        everything = [r for pool in self.pools.values() for r in pool]
        self.macros = {r.id: _macros(r) for r in everything}
        self.grams = {r.id: r.grams_by_ingredient() for r in everything}
        self.prices = (
            {
                key: (float(p.price_per_gram * p.package_grams), float(p.package_grams), float(p.price_per_gram))
                for key, p in prices.items()
            }
            if prices is not None
            else None
        )

    # -- scoring ----------------------------------------------------------------------------------

    def package_cost(self, key: str, grams: float) -> float:
        if self.prices is None or grams <= 1e-9:
            return 0.0
        package_price, package_grams, _ = self.prices[key]
        return ceil(round(grams, 3) / package_grams) * package_price

    def food_cost(self, key: str, grams: float) -> float:
        """What the grams themselves cost, ignoring packages (only used to break ties when over budget)."""
        return grams * self.prices[key][2] if self.prices is not None else 0.0

    def day_miss(self, day: int, totals: list[float]) -> float:
        return sum(abs(actual - target) / target for actual, target in zip(totals, self.targets[day], strict=True))

    def key(self, cost: float, avoided: int, miss: float, food: float) -> tuple:
        over = max(cost - self.budget, 0.0) if self.budget is not None else 0.0
        return (round(over, 6), avoided, round(food, 6) if over > 0 else 0.0, round(miss, 9), round(cost, 6))

    def state(self, assign: list[tuple[Recipe, Decimal]]) -> '_State':
        """Everything the moves need, worked out from scratch."""
        state = _State(assign=list(assign))
        for (day, _), (recipe, portion) in zip(self.slots, assign, strict=True):
            state.uses[recipe.id] += 1
            state.day_recipes[day][recipe.id] += 1
            for key, grams in self.grams[recipe.id].items():
                state.need[key] = state.need.get(key, 0.0) + grams * float(portion)
            for i, value in enumerate(self.macros[recipe.id]):
                state.day_totals[day][i] += value * float(portion)
        state.cost = sum(self.package_cost(k, g) for k, g in state.need.items())
        state.food = sum(self.food_cost(k, g) for k, g in state.need.items())
        state.misses = [self.day_miss(day, state.day_totals[day]) for day in range(len(DAY_NAMES))]
        state.avoided = sum(1 for recipe, _ in assign if recipe.id in self.avoid)
        state.key = self.key(state.cost, state.avoided, sum(state.misses), state.food)
        return state

    # -- search -----------------------------------------------------------------------------------

    def run(self, rng: random.Random) -> tuple[tuple, list[tuple[Recipe, Decimal]]]:
        state = self.state(self._random_start(rng))
        order = list(range(len(self.slots)))
        rng.shuffle(order)
        for _ in range(MAX_PASSES):
            self._meal_moves(state, order)
            better = self._recipe_move(state)
            if better is None:
                break
            state = better
        return state.key, state.assign

    def _random_start(self, rng: random.Random) -> list[tuple[Recipe, Decimal]]:
        assign: list[tuple[Recipe, Decimal]] = []
        uses: Counter = Counter()
        day_recipes: dict[int, Counter] = {day: Counter() for day in range(len(DAY_NAMES))}
        for day, meal in self.slots:
            course = COURSE_FOR_MEAL[meal]
            choices = [o for o in self.options[course] if self._allowed(o[0], course, day, uses, day_recipes)]
            # The day rule is the one that can corner a random start; drop it for this meal if it has to go.
            choices = choices or [o for o in self.options[course] if uses[o[0].id] < self.cap[course]]
            choice = rng.choice(choices)
            assign.append(choice)
            uses[choice[0].id] += 1
            day_recipes[day][choice[0].id] += 1
        return assign

    def _meal_moves(self, state: '_State', order: list[int]) -> None:
        """Swap single meals (recipe and portion) for better ones until no single swap helps."""
        for _ in range(MAX_PASSES):
            improved = False
            for index in order:
                if self._best_meal_move(state, index):
                    improved = True
            if not improved:
                return

    def _best_meal_move(self, state: '_State', index: int) -> bool:
        day, meal = self.slots[index]
        course = COURSE_FOR_MEAL[meal]
        old_recipe, old_portion = state.assign[index]
        state.uses[old_recipe.id] -= 1
        state.day_recipes[day][old_recipe.id] -= 1
        best = None
        for option in self.options[course]:
            recipe, portion = option
            if option == state.assign[index] or not self._allowed(recipe, course, day, state.uses, state.day_recipes):
                continue
            new_cost, new_food, changed = state.cost, state.food, {}
            if self.prices is not None:
                for k in self.grams[old_recipe.id].keys() | self.grams[recipe.id].keys():
                    grams = (
                        state.need.get(k, 0.0)
                        - self.grams[old_recipe.id].get(k, 0.0) * float(old_portion)
                        + self.grams[recipe.id].get(k, 0.0) * float(portion)
                    )
                    changed[k] = grams
                    new_cost += self.package_cost(k, grams) - self.package_cost(k, state.need.get(k, 0.0))
                    new_food += self.food_cost(k, grams) - self.food_cost(k, state.need.get(k, 0.0))
            totals = [
                state.day_totals[day][i]
                - self.macros[old_recipe.id][i] * float(old_portion)
                + self.macros[recipe.id][i] * float(portion)
                for i in range(3)
            ]
            day_miss = self.day_miss(day, totals)
            avoided = state.avoided - (old_recipe.id in self.avoid) + (recipe.id in self.avoid)
            key = self.key(new_cost, avoided, sum(state.misses) - state.misses[day] + day_miss, new_food)
            if key < (best[0] if best else state.key):
                best = (key, option, new_cost, new_food, changed, totals, day_miss, avoided)
        if best is None:
            state.uses[old_recipe.id] += 1
            state.day_recipes[day][old_recipe.id] += 1
            return False
        state.key, option, state.cost, state.food, changed, state.day_totals[day], state.misses[day], state.avoided = (
            best
        )
        state.need.update(changed)  # empty without prices: grams only matter for cost
        state.assign[index] = option
        state.uses[option[0].id] += 1
        state.day_recipes[day][option[0].id] += 1
        return True

    def _recipe_move(self, state: '_State') -> '_State | None':
        """The best swap of one recipe for another everywhere it's used, or None if none helps.

        A recipe is often used twice, so swapping one meal can't stop buying its ingredients; swapping every use at
        once can. This is what lets the search find cheaper weeks built on shared ingredients.
        """
        best = None
        for old_id in sorted(state.uses):
            if state.uses[old_id] <= 0:
                continue
            indexes = [i for i, (recipe, _) in enumerate(state.assign) if recipe.id == old_id]
            course = COURSE_FOR_MEAL[self.slots[indexes[0]][1]]
            days = {self.slots[i][0] for i in indexes}
            for recipe in self.pools[course]:
                if recipe.id == old_id or state.uses[recipe.id] + len(indexes) > self.cap[course]:
                    continue
                if self.unique_per_day[course] and any(state.day_recipes[d][recipe.id] for d in days):
                    continue
                assign = list(state.assign)
                for i in indexes:
                    assign[i] = (recipe, assign[i][1])
                candidate = self.state(assign)
                if candidate.key < (best.key if best else state.key):
                    best = candidate
        return best

    def _allowed(self, recipe: Recipe, course: str, day: int, uses: Counter, day_recipes: dict[int, Counter]) -> bool:
        if uses[recipe.id] >= self.cap[course]:
            return False
        return not (self.unique_per_day[course] and day_recipes[day][recipe.id] > 0)


def _empty_days() -> dict[int, Counter]:
    return {day: Counter() for day in range(len(DAY_NAMES))}


def _zero_totals() -> list[list[float]]:
    return [[0.0, 0.0, 0.0] for _ in DAY_NAMES]


@dataclass
class _State:
    assign: list[tuple[Recipe, Decimal]]
    uses: Counter = field(default_factory=Counter)
    day_recipes: dict[int, Counter] = field(default_factory=_empty_days)
    need: dict[str, float] = field(default_factory=dict)
    day_totals: list[list[float]] = field(default_factory=_zero_totals)
    misses: list[float] = field(default_factory=list)
    avoided: int = 0
    cost: float = 0.0
    food: float = 0.0
    key: tuple = ()


def _macros(recipe: Recipe) -> tuple[float, float, float]:
    n = recipe.nutrients
    return (n.protein_g, n.carbs_g, n.fat_g)
