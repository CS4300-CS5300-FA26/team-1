"""The meal plan report: budget use, daily spend, and the week's ingredients (pure; no I/O)."""

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from .domain import CENT, MealPlan, PlannedDay, PlannedMeal, RecipeDetails, money

# Characters that make spreadsheet apps treat a cell as a formula (CSV/formula injection).
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


@dataclass(frozen=True)
class DayUsage:
    day: PlannedDay
    percent_of_daily_budget: int  # 0 when the budget is $0
    bar_percent: float  # bar length on the shared scale (0-100)


@dataclass(frozen=True)
class MealIngredients:
    day: PlannedDay
    meal: PlannedMeal
    details: RecipeDetails | None  # None when the recipe source can't provide them right now


@dataclass(frozen=True)
class MealPlanReport:
    plan: MealPlan
    days: tuple[DayUsage, ...]
    daily_budget: Decimal
    daily_budget_marker_percent: float  # where the daily budget falls on the day bars' scale
    meals: tuple[MealIngredients, ...]

    @property
    def remaining(self) -> Decimal:
        return max(money(self.plan.budget - self.plan.total_cost), Decimal('0.00'))

    @property
    def percent_used(self) -> int:
        """Share of the budget the plan uses (can exceed 100); 0 for a $0 budget."""
        if self.plan.budget <= 0:
            return 0
        return round(self.plan.total_cost / self.plan.budget * 100)

    @property
    def meter_percent(self) -> int:
        """How full the budget meter is drawn: capped at 100."""
        return 100 if self.plan.budget <= 0 else min(self.percent_used, 100)

    @property
    def ingredient_count(self) -> int:
        return sum(len(m.details.ingredients) for m in self.meals if m.details)

    @property
    def missing_details(self) -> int:
        return sum(1 for m in self.meals if m.details is None)


def build_report(plan: MealPlan, details_for: Callable[[PlannedMeal], RecipeDetails | None]) -> MealPlanReport:
    daily_budget = (plan.budget / len(plan.days)).quantize(CENT) if plan.days else Decimal('0.00')
    # One shared scale for every day bar: the biggest day or the daily budget line, plus a little
    # headroom so neither touches the edge.
    scale = max([day.cost for day in plan.days] + [daily_budget, CENT]) * Decimal('1.08')
    days = tuple(
        DayUsage(
            day=day,
            percent_of_daily_budget=round(day.cost / daily_budget * 100) if daily_budget > 0 else 0,
            bar_percent=float(day.cost / scale * 100),
        )
        for day in plan.days
    )
    meals = tuple(MealIngredients(day, meal, details_for(meal)) for day in plan.days for meal in day.meals)
    return MealPlanReport(
        plan=plan,
        days=days,
        daily_budget=daily_budget,
        daily_budget_marker_percent=float(daily_budget / scale * 100),
        meals=meals,
    )


def safe_cell(value: object) -> str:
    """A CSV cell that spreadsheet apps will show as text, never run as a formula."""
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def ingredients_csv(report: MealPlanReport) -> str:
    """The week's ingredients, one row per ingredient line, as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['Day', 'Meal', 'Recipe', 'Ingredient', 'Cost per serving (USD)'])
    rows: Iterable[list[object]] = (
        [entry.day.day_name, entry.meal.meal.capitalize(), entry.meal.recipe.title, line.text, entry.meal.cost]
        for entry in report.meals
        if entry.details
        for line in entry.details.ingredients
    )
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return buffer.getvalue()
