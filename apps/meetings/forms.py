from django import forms

from apps.core.forms import BootstrapMixin, DateInput, MultiFileField
from apps.organization.models import Employee

from .models import COMMITTEES, Meeting, MeetingDecision


class MeetingForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Meeting
        fields = ["number", "title", "committee", "date", "location", "external_ref", "notes"]
        widgets = {"date": DateInput(), "notes": forms.Textarea(attrs={"rows": 2}),
                   "committee": forms.TextInput(attrs={"list": "committees"})}


class DecisionForm(BootstrapMixin, forms.ModelForm):
    attachments = MultiFileField(label="المرفقات")

    class Meta:
        model = MeetingDecision
        fields = ["number", "meeting", "text", "decision_date", "due_date", "followup_owner"]
        widgets = {"decision_date": DateInput(), "due_date": DateInput(), "text": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["followup_owner"].queryset = Employee.objects.order_by("full_name")
        self.fields["followup_owner"].widget.attrs["data-enhance"] = "1"
        self.fields["meeting"].widget.attrs["data-enhance"] = "1"


COMMITTEE_CHOICES = COMMITTEES
