"""D-4 connector for the meal plan: the daily macro targets from this week's plan (ADR-012).

Wired through `NUTRITION_MACRO_TARGETS_PROVIDER` (see `nutrition.ports.MacroTargetsProvider` and ADR-008), so the
meal plan aims at the same protein, carbs and fat the This Week and Nutrition pages show. `nutrition` never imports
this app; it only knows the class by its dotted path.
"""

import logging
from collections.abc import Sequence
from datetime import date

from core.models import UserProfile
from nutrition.domain import DAY_NAMES, MacroTargets

from .generator import PlanGenerationError, generate_plan
from .models import WeeklyPlan

logger = logging.getLogger(__name__)


class PlanMacroTargets:
    """Seven copies of the plan's daily target, Monday first, or None when the user has no plan yet.

    The plan has one daily target for the whole week (the Nutrition page shows it), so every day gets the same one.
    Called on every Meal Plan page view, so it never writes: it reads the week's saved plan, and if the user hasn't
    opened This Week yet it calculates the targets that page would save, from the same profile. The starter plan's
    targets aren't personal, so a failed generation returns None and the meal plan uses its own fallback.
    """

    def weekly_targets(self, user, week_start: date) -> Sequence[MacroTargets] | None:
        macros = self._plan_macros(user, week_start)
        if macros is None:
            return None
        try:
            daily = MacroTargets(protein_g=macros['protein'], carbs_g=macros['carbs'], fat_g=macros['fat'])
        except (KeyError, TypeError, ValueError):
            logger.warning('Plan macros for user %s are incomplete; the meal plan will use its fallback', user.pk)
            return None
        return [daily for _ in DAY_NAMES]

    @staticmethod
    def _plan_macros(user, week_start: date) -> dict | None:
        saved = WeeklyPlan.objects.filter(user=user, week_start=week_start).only('data').first()
        if saved is not None:
            return saved.data.get('macros')

        profile = UserProfile.objects.filter(user=user, onboarding_completed=True).first()
        if profile is None:
            return None
        try:
            return generate_plan(profile)['macros']
        except PlanGenerationError:
            return None
