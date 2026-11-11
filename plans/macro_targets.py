"""D-4 connector for the meal plan: the daily macro targets from this week's plan (ADR-012).

Wired through `NUTRITION_MACRO_TARGETS_PROVIDER` (see `nutrition.ports.MacroTargetsProvider` and ADR-008), so the
meal plan aims at the same protein, carbs and fat the This Week and Nutrition pages show. `nutrition` never imports
this app; it only knows the class by its dotted path.
"""

import logging
from collections.abc import Sequence
from datetime import date

from nutrition.domain import DAY_NAMES, MacroTargets

from .models import WeeklyPlan

logger = logging.getLogger(__name__)


class PlanMacroTargets:
    """Seven copies of the saved plan's daily target, Monday first, or None when the user has no plan this week.

    The plan has one daily target for the whole week (the Nutrition page shows it), so every day gets the same one.
    Only a saved plan counts: until the user's first visit to This Week or Nutrition creates one, there is no plan
    yet and the meal plan uses its published fallback (D-4's "No plan yet"). Called on every Meal Plan page view, so
    it only reads. Starter plans are never saved, so their general targets never reach the meal plan.
    """

    def weekly_targets(self, user, week_start: date) -> Sequence[MacroTargets] | None:
        saved = WeeklyPlan.objects.filter(user=user, week_start=week_start).only('data').first()
        if saved is None:
            return None
        try:
            macros = saved.data['macros']
            daily = MacroTargets(protein_g=macros['protein'], carbs_g=macros['carbs'], fat_g=macros['fat'])
        except (KeyError, TypeError, ValueError):
            logger.warning('Saved plan macros for user %s are unusable; the meal plan will use its fallback', user.pk)
            return None
        return [daily for _ in DAY_NAMES]
