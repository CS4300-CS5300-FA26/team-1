"""Placeholder macro targets provider, used until D-4 (macro generation) exists.

D-4 should add a class with the same `weekly_targets(user, week_start)` method (see
`nutrition.ports.MacroTargetsProvider`) and point NUTRITION_MACRO_TARGETS_PROVIDER at it.
"""


class NoMacroTargets:
    """Nobody has macro targets yet, so meal plans are optimised for cost alone."""

    def weekly_targets(self, user, week_start):
        return None
