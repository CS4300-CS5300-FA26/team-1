"""Default connectors for features that aren't built yet (see ports.py and ADR-008).

Each says "nothing to offer yet"; the meal plan then falls back (published Daily Values for macro targets, no
costs for prices) and tells the user. Replace a default by pointing its setting at the real implementation.
"""


class NoMacroTargets:
    """Until D-4 (macro generation) is connected: no personal targets."""

    def weekly_targets(self, user, week_start):
        return None


class NoGroceryPrices:
    """Until D-6 (grocery list) is connected: no prices."""

    def quotes(self, ingredients):
        return {}
