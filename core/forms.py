from django import forms

from .models import EQUIPMENT_CHOICES, MEAL_PATTERN_CHOICES, UserProfile


class OnboardingForm(forms.ModelForm):
    """Onboarding questionnaire. Every question is required."""

    # Height and weight are bounded here, not on the model, so the limits can change
    # without a migration. Generous ranges that still catch typos like 0 or 7000.
    height_inches = forms.IntegerField(
        label='Height (inches)',
        min_value=36,
        max_value=96,
        error_messages={'required': 'Your height is required.'},
    )
    weight = forms.DecimalField(
        label='Weight (lb)',
        min_value=50,
        max_value=700,
        max_digits=5,
        decimal_places=2,
        error_messages={'required': 'Your weight is required.'},
    )
    weekly_food_budget = forms.DecimalField(
        label='Weekly food budget ($)',
        min_value=0,
        max_digits=7,
        decimal_places=2,
        error_messages={'required': 'Weekly food budget is required.'},
    )
    equipment = forms.MultipleChoiceField(
        label='Available equipment',
        choices=EQUIPMENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        error_messages={'required': 'Select at least one option for available equipment.'},
    )

    meal_pattern = forms.ChoiceField(
        label='Which meals should your meal plan cover?',
        choices=MEAL_PATTERN_CHOICES,
        widget=forms.RadioSelect,
        error_messages={'required': 'Choose which meals to plan.'},
    )

    class Meta:
        model = UserProfile
        fields = [
            'goal',
            'height_inches',
            'weight',
            'experience_level',
            'weekly_food_budget',
            'meal_pattern',
            'equipment',
        ]
        labels = {
            'goal': 'Your goal',
            'experience_level': 'Experience level',
        }
        error_messages = {
            'goal': {'required': 'Your goal is required.'},
            'experience_level': {'required': 'Your experience level is required.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The model fields are blank=True (they're empty until onboarding), which would make
        # the form treat them as optional, so require every question here.
        for field in self.fields.values():
            field.required = True

    def clean_equipment(self):
        equipment = self.cleaned_data['equipment']
        if 'none' in equipment and len(equipment) > 1:
            raise forms.ValidationError('"No equipment" can\'t be combined with other equipment.')
        return equipment
