
from django import forms

from runs.models import AgentRun


class RunCreateForm(forms.ModelForm):
    max_steps = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=20,
        label="Maximum steps",
    )
    max_tool_invocations = forms.IntegerField(
        min_value=1,
        max_value=500,
        initial=50,
        label="Maximum tool invocations",
    )
    max_runtime_seconds = forms.IntegerField(
        min_value=1,
        max_value=86400,
        initial=900,
        label="Maximum runtime (seconds)",
    )

    class Meta:
        model = AgentRun
        fields = [
            "objective",
            "max_steps",
            "max_tool_invocations",
            "max_runtime_seconds",
        ]
        widgets = {
            "objective": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 500,
                    "placeholder": (
                        "Describe the outcome you want Saffron to achieve..."
                    ),
                }
            ),
        }

    def clean_objective(self):
        objective = self.cleaned_data["objective"].strip()
        if not objective:
            raise forms.ValidationError("Enter a workflow objective.")
        return objective
