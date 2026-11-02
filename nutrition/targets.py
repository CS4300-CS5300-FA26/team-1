"""Daily macro targets used while the macro connector (D-4) has none for a user.

These are the FDA Daily Values for adults and children 4 years and older, for a 2,000-calorie reference diet:
total fat 78 g, total carbohydrate 275 g, protein 50 g. They are what US nutrition labels use.
Source: 21 CFR 101.9(c), https://www.ecfr.gov/current/title-21/chapter-I/subchapter-B/part-101/subpart-A/section-101.9
and https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels
"""

from .domain import DAY_NAMES, MacroTargets

DAILY_VALUES = MacroTargets(protein_g=50, carbs_g=275, fat_g=78)
DAILY_VALUES_KCAL = 2000
DAILY_VALUES_SOURCE = 'FDA Daily Values for a 2,000-calorie diet'


def published_weekly_targets() -> tuple[MacroTargets, ...]:
    return tuple(DAILY_VALUES for _ in DAY_NAMES)
