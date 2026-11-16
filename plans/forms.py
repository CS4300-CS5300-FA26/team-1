from django import forms

from .generator import SPLIT_LABELS
from .services import NEXT_SPLIT


class SplitChoiceForm(forms.Form):
    """Which split to use this week: one of the styles, or NEXT_SPLIT for "Switch it up"."""

    split = forms.ChoiceField(choices=[(NEXT_SPLIT, 'Next split'), *SPLIT_LABELS.items()])
