from django.conf import settings
from django.db import models
from django.db.models import Q

from .domain import COURSES, DAY_NAMES, MEALS


class Ingredient(models.Model):
    """A food recipes use, with nutrients per 100 g copied from USDA FoodData Central (`fdc_id`).

    `grams_per_ml` and `grams_per_each` come from FoodData Central portion weights; they let price quotes sold by
    volume or count be converted to grams (see pricing.py).
    """

    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    fdc_id = models.PositiveIntegerField()
    fdc_description = models.CharField(max_length=200)
    kcal_per_100g = models.DecimalField(max_digits=6, decimal_places=2)
    protein_per_100g = models.DecimalField(max_digits=6, decimal_places=2)
    carbs_per_100g = models.DecimalField(max_digits=6, decimal_places=2)
    fat_per_100g = models.DecimalField(max_digits=6, decimal_places=2)
    grams_per_ml = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    grams_per_each = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.CheckConstraint(
                condition=Q(kcal_per_100g__gte=0, protein_per_100g__gte=0, carbs_per_100g__gte=0, fat_per_100g__gte=0)
                & Q(protein_per_100g__lte=100, carbs_per_100g__lte=100, fat_per_100g__lte=100),
                name='nutrition_ingredient_nutrients_in_range',
            ),
            models.CheckConstraint(
                condition=(Q(grams_per_ml__isnull=True) | Q(grams_per_ml__gt=0))
                & (Q(grams_per_each__isnull=True) | Q(grams_per_each__gt=0)),
                name='nutrition_ingredient_densities_positive',
            ),
        ]

    def __str__(self):
        return self.name


class CatalogRecipe(models.Model):
    """A recipe in FitPro's catalog. Its lines are for one serving."""

    slug = models.SlugField(max_length=60, unique=True)
    title = models.CharField(max_length=200)
    course = models.CharField(max_length=10, choices=[(c, c.capitalize()) for c in COURSES])
    ready_in_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    steps = models.JSONField(default=list)

    class Meta:
        ordering = ['course', 'title']

    def __str__(self):
        return self.title


class RecipeLine(models.Model):
    """One ingredient line of a recipe, for one serving. A line with no ingredient (salt, spices) has no weight."""

    recipe = models.ForeignKey(CatalogRecipe, on_delete=models.CASCADE, related_name='lines')
    position = models.PositiveSmallIntegerField()
    text = models.CharField(max_length=300)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, null=True, blank=True, related_name='lines')
    grams = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['recipe', 'position']
        constraints = [
            models.UniqueConstraint(fields=['recipe', 'position'], name='nutrition_one_line_per_position'),
            models.CheckConstraint(
                condition=Q(ingredient__isnull=True, grams__isnull=True) | Q(ingredient__isnull=False, grams__gt=0),
                name='nutrition_line_weighed_with_ingredient',
            ),
        ]

    def __str__(self):
        return self.text


class WeeklyMealPlan(models.Model):
    """A user's meal plan for the week starting `week_start` (a Monday). D-6 builds its grocery list from it.

    `inputs` records what the plan was made for (budget, meals, daily targets, whether prices were connected);
    when any of them changes, a new plan is made. `seed` makes the planner's search repeatable.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='meal_plans')
    week_start = models.DateField()
    created_at = models.DateTimeField(auto_now=True)
    inputs = models.JSONField(default=dict)
    seed = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-week_start']
        constraints = [models.UniqueConstraint(fields=['user', 'week_start'], name='nutrition_one_plan_per_week')]

    def __str__(self):
        return f'{self.user} week of {self.week_start}'


class PlannedMealEntry(models.Model):
    """One meal of a weekly plan.

    `recipe_id` is the recipe source's id (a catalog slug today), not a foreign key, so any recipe source can be
    plugged in. If the source no longer has the recipe, the stored plan is ignored and a new one is made.
    """

    plan = models.ForeignKey(WeeklyMealPlan, on_delete=models.CASCADE, related_name='entries')
    day = models.PositiveSmallIntegerField(choices=list(enumerate(DAY_NAMES)))
    meal = models.CharField(max_length=10, choices=[(m, m.capitalize()) for m in MEALS])
    recipe_id = models.CharField(max_length=100)
    servings = models.DecimalField(max_digits=3, decimal_places=1)

    class Meta:
        ordering = ['plan', 'day', 'meal']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'day', 'meal'], name='nutrition_one_entry_per_meal'),
            models.CheckConstraint(condition=Q(day__lte=6), name='nutrition_entry_day_in_week'),
            models.CheckConstraint(condition=Q(servings__gt=0), name='nutrition_entry_servings_positive'),
        ]

    def __str__(self):
        return f'{DAY_NAMES[self.day]} {self.meal}: {self.recipe_id}'
