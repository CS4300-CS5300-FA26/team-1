from decimal import Decimal

from django import forms
from django.forms import BoundField

from .domain import DAYS_PER_WEEK_CHOICES, MAX_MINUTES, MAX_REPS, MAX_WEIGHT_LB
from .services import ExerciseLog


class PreferencesForm(forms.Form):
    """How many days a week the user wants to train."""

    days_per_week = forms.TypedChoiceField(
        label='Training days per week',
        choices=[(n, f'{n} days') for n in DAYS_PER_WEEK_CHOICES],
        coerce=int,
        error_messages={'invalid_choice': 'Choose 3, 4, or 5 days.', 'required': 'Choose how many days to train.'},
    )


class SessionLogForm(forms.Form):
    """The sets of one workout: reps and weight per strength set, minutes per cardio exercise.

    Every field is optional, because a set that isn't done stays empty. Field names are built from the planned
    exercise's id and the set number, so a user can only ever post values for the rows this form was built with.
    """

    def __init__(self, logs: list[ExerciseLog], *args, finishing: bool = False, has_saved_sets: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.logs = logs
        self.finishing = finishing
        self.has_saved_sets = has_saved_sets
        for log in logs:
            for row in log.rows:
                if log.planned.is_timed:
                    self.fields[self.key('minutes', log.planned.pk, row.number)] = forms.IntegerField(
                        label='Minutes done',
                        required=False,
                        min_value=1,
                        max_value=MAX_MINUTES,
                        initial=row.minutes,
                    )
                else:
                    self.fields[self.key('reps', log.planned.pk, row.number)] = forms.IntegerField(
                        label='Reps', required=False, min_value=1, max_value=MAX_REPS, initial=row.reps
                    )
                    self.fields[self.key('weight', log.planned.pk, row.number)] = forms.DecimalField(
                        label='Weight (lb)',
                        required=False,
                        min_value=0,
                        max_value=MAX_WEIGHT_LB,
                        max_digits=6,
                        decimal_places=1,
                        initial=row.weight_lb,
                    )

    @staticmethod
    def key(kind: str, planned_id: int, number: int) -> str:
        return f'{kind}_{planned_id}_{number}'

    def blocks(self) -> list[dict]:
        """Each exercise with its set rows and their bound fields, for the template."""
        blocks = []
        for log in self.logs:
            rows = []
            for row in log.rows:
                bound: dict[str, BoundField | None] = {
                    kind: self[self.key(kind, log.planned.pk, row.number)]
                    if self.key(kind, log.planned.pk, row.number) in self.fields
                    else None
                    for kind in ('reps', 'weight', 'minutes')
                }
                rows.append({'number': row.number, **bound})
            blocks.append({'log': log, 'rows': rows})
        return blocks

    def clean(self):
        super().clean()
        cleaned = self.cleaned_data
        entries = self.entries()
        for log in self.logs:
            for row in log.rows:
                reps_key = self.key('reps', log.planned.pk, row.number)
                weight_key = self.key('weight', log.planned.pk, row.number)
                if (
                    reps_key in self.fields
                    and reps_key not in self.errors
                    and weight_key not in self.errors
                    and cleaned.get(weight_key) is not None
                    and not cleaned.get(reps_key)
                ):
                    self.add_error(reps_key, 'Enter the reps for this set, or clear its weight.')
        if (
            self.finishing
            and not self.errors
            and not self.has_saved_sets
            and not any(reps or minutes for reps, _, minutes in entries.values())
        ):
            raise forms.ValidationError('Log at least one set before finishing the workout.')
        return cleaned

    def entries(self) -> dict[tuple[int, int], tuple[int | None, Decimal | None, int | None]]:
        """(exercise id, set number) -> (reps, weight, minutes) for every row, from the cleaned data."""
        data = getattr(self, 'cleaned_data', {})
        entries = {}
        for log in self.logs:
            for row in log.rows:
                entries[(log.planned.exercise_id, row.number)] = (
                    data.get(self.key('reps', log.planned.pk, row.number)),
                    data.get(self.key('weight', log.planned.pk, row.number)),
                    data.get(self.key('minutes', log.planned.pk, row.number)),
                )
        return entries
