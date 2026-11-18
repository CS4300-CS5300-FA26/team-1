from django import forms
from django.forms import BoundField

from .domain import MAX_MINUTES, MAX_REPS, MAX_SECONDS, MAX_WEIGHT_LB, MINUTES, SECONDS
from .services import Entries, ExerciseLog

KINDS = ('reps', 'weight', 'seconds', 'minutes')


class SessionLogForm(forms.Form):
    """The sets of one workout: reps and weight per strength set, seconds per hold, minutes for cardio.

    Every field is optional, because a set that isn't done stays empty. Field names are built from the exercise's
    position in the workout and the set number, so a user can only ever post values for the rows this form was built
    with.
    """

    def __init__(self, logs: list[ExerciseLog], *args, finishing: bool = False, has_saved_sets: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.logs = logs
        self.finishing = finishing
        self.has_saved_sets = has_saved_sets
        for log in logs:
            for row in log.rows:
                if log.target.kind == MINUTES:
                    self.fields[self.key('minutes', log.position, row.number)] = forms.IntegerField(
                        label='Minutes done', required=False, min_value=1, max_value=MAX_MINUTES, initial=row.minutes
                    )
                elif log.target.kind == SECONDS:
                    self.fields[self.key('seconds', log.position, row.number)] = forms.IntegerField(
                        label='Seconds held', required=False, min_value=1, max_value=MAX_SECONDS, initial=row.seconds
                    )
                else:
                    self.fields[self.key('reps', log.position, row.number)] = forms.IntegerField(
                        label='Reps', required=False, min_value=1, max_value=MAX_REPS, initial=row.reps
                    )
                    self.fields[self.key('weight', log.position, row.number)] = forms.DecimalField(
                        label='Weight (lb)',
                        required=False,
                        min_value=0,
                        max_value=MAX_WEIGHT_LB,
                        max_digits=6,
                        decimal_places=1,
                        initial=row.weight_lb,
                    )

    @staticmethod
    def key(kind: str, position: int, number: int) -> str:
        return f'{kind}_{position}_{number}'

    def blocks(self) -> list[dict]:
        """Each exercise with its set rows and their bound fields, for the template."""
        blocks = []
        for log in self.logs:
            rows = []
            for row in log.rows:
                bound: dict[str, BoundField | None] = {
                    kind: self[self.key(kind, log.position, row.number)]
                    if self.key(kind, log.position, row.number) in self.fields
                    else None
                    for kind in KINDS
                }
                rows.append({'number': row.number, **bound})
            blocks.append({'log': log, 'rows': rows})
        return blocks

    def names(self) -> dict[int, str]:
        return {log.position: log.name for log in self.logs}

    def clean(self):
        super().clean()
        cleaned = self.cleaned_data
        for log in self.logs:
            for row in log.rows:
                reps_key = self.key('reps', log.position, row.number)
                weight_key = self.key('weight', log.position, row.number)
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
            and not any(reps or seconds or minutes for reps, _, seconds, minutes in self.entries().values())
        ):
            raise forms.ValidationError('Log at least one set before finishing the workout.')
        return cleaned

    def entries(self) -> Entries:
        """(position, set number) -> (reps, weight, seconds, minutes) for every row, from the cleaned data."""
        data = getattr(self, 'cleaned_data', {})
        return {
            (log.position, row.number): (
                data.get(self.key('reps', log.position, row.number)),
                data.get(self.key('weight', log.position, row.number)),
                data.get(self.key('seconds', log.position, row.number)),
                data.get(self.key('minutes', log.position, row.number)),
            )
            for log in self.logs
            for row in log.rows
        }
