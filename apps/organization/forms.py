from django import forms

from apps.core.files import validate_upload
from apps.core.forms import BootstrapMixin, DateInput

from .models import Employee, Unit


class UnitForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["name", "code", "description", "head", "parent", "is_active", "established_on", "sort_order"]
        widgets = {"established_on": DateInput(), "description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["head"].queryset = Employee.objects.order_by("full_name")
        self.fields["head"].widget.attrs["data-enhance"] = "1"
        if self.instance.pk:
            self.fields["parent"].queryset = Unit.objects.exclude(pk=self.instance.pk)


class EmployeeForm(BootstrapMixin, forms.ModelForm):
    units = forms.ModelMultipleChoiceField(label="الوحدات", queryset=Unit.objects.filter(is_active=True), required=True,
                                           help_text="يمكن ربط الموظف بأكثر من وحدة؛ الأولى المختارة أدناه هي الأساسية")
    primary_unit = forms.ModelChoiceField(label="الوحدة الأساسية", queryset=Unit.objects.filter(is_active=True))

    class Meta:
        model = Employee
        fields = ["full_name", "employee_no", "job_title", "manager", "join_date", "status", "photo"]
        widgets = {"join_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = Employee.objects.exclude(pk=self.instance.pk).order_by("full_name")
        self.fields["units"].widget.attrs["data-enhance"] = "1"
        self.fields["manager"].widget.attrs["data-enhance"] = "1"
        if self.instance.pk:
            self.fields["units"].initial = list(self.instance.units.values_list("pk", flat=True))
            self.fields["primary_unit"].initial = getattr(self.instance.primary_unit, "pk", None)

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and not getattr(photo, "_committed", True):
            if validate_upload(photo) != "image":
                raise forms.ValidationError("الصورة يجب أن تكون PNG أو JPG")
        return photo

    def clean(self):
        data = super().clean()
        if data.get("primary_unit") and data.get("units") is not None and data["primary_unit"] not in data["units"]:
            data["units"] = list(data["units"]) + [data["primary_unit"]]
        return data
