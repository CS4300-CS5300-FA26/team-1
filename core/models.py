# Create your models here.
from django.contrib.auth.models import User
from django.db import models

GOAL_CHOICES = [
    ('lose_weight', 'Lose weight'),
    ('build_muscle', 'Build muscle'),
    ('maintain', 'Maintain my weight'),
    ('endurance', 'Improve endurance'),
]

EXPERIENCE_CHOICES = [
    ('beginner', 'Beginner'),
    ('intermediate', 'Intermediate'),
    ('advanced', 'Advanced'),
]

EQUIPMENT_CHOICES = [
    ('none', 'No equipment (bodyweight only)'),
    ('dumbbells', 'Dumbbells'),
    ('barbell', 'Barbell and rack'),
    ('machines', 'Gym machines'),
    ('bands', 'Resistance bands'),
    ('cardio', 'Cardio equipment'),
]


class UserProfile(models.Model):
    # username etup with a max length of 100 until we set actual limits
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Age/weight setup to allow empty age/weight fields in the database for now, can adjust later if needed
    age = models.PositiveIntegerField(null=True, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    onboarding_completed = models.BooleanField(default=False)

    # Onboarding answers: empty until the user finishes the questionnaire.
    goal = models.CharField(max_length=20, choices=GOAL_CHOICES, blank=True)
    height_inches = models.PositiveSmallIntegerField(null=True, blank=True)
    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_CHOICES, blank=True)
    weekly_food_budget = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)  # dollars
    equipment = models.JSONField(default=list, blank=True)  # list of EQUIPMENT_CHOICES keys

    def __str__(self):
        return f'{self.user.username} (Age: {self.age}, Weight: {self.weight})'

    def equipment_labels(self):
        """Human-readable equipment names for the profile summary."""
        labels = dict(EQUIPMENT_CHOICES)
        return [labels.get(key, key) for key in self.equipment]
