from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import Role, User, normalize_phone
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
                                           help_text="يمكن ربط الموظف بأكثر من وحدة")
    primary_unit = forms.ModelChoiceField(label="الوحدة الأساسية", queryset=Unit.objects.filter(is_active=True))
    is_unit_head = forms.BooleanField(label="رئيس الوحدة الأساسية", required=False)

    # حساب الدخول
    has_account = forms.BooleanField(label="للموظف حساب دخول إلى المنصة", required=False, initial=True)
    email = forms.EmailField(label="البريد الإلكتروني", required=False)
    phone = forms.CharField(label="رقم الجوال", max_length=20, required=False)
    role = forms.ModelChoiceField(label="الدور", queryset=Role.objects.all(), required=False)
    password = forms.CharField(label="كلمة مرور مؤقتة", required=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text="سيُطلب من الموظف تغييرها عند أول دخول")
    account_active = forms.BooleanField(label="الحساب نشط", required=False, initial=True)

    class Meta:
        model = Employee
        fields = ["full_name", "employee_no", "job_title", "manager", "join_date", "status", "photo"]
        widgets = {"join_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = Employee.objects.exclude(pk=self.instance.pk).order_by("full_name")
        self.fields["units"].widget.attrs["data-enhance"] = "1"
        self.fields["manager"].widget.attrs["data-enhance"] = "1"
        self.fields["role"].initial = Role.objects.filter(code="employee").first()
        self.user = self.instance.user if self.instance.pk and self.instance.user_id else None
        if self.instance.pk:
            self.fields["units"].initial = list(self.instance.units.values_list("pk", flat=True))
            primary = self.instance.primary_unit
            self.fields["primary_unit"].initial = getattr(primary, "pk", None)
            self.fields["is_unit_head"].initial = bool(primary and primary.head_id == self.instance.pk)
        if self.user:
            self.fields["has_account"].initial = True
            self.fields["email"].initial = self.user.email
            self.fields["phone"].initial = self.user.phone
            self.fields["role"].initial = self.user.role
            self.fields["account_active"].initial = self.user.is_active
            self.fields["password"].label = "إعادة تعيين كلمة المرور (اختياري)"

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
        if data.get("has_account"):
            exclude = self.user.pk if self.user else None
            if not data.get("email"):
                self.add_error("email", "البريد الإلكتروني مطلوب لحساب الدخول")
            elif User.objects.exclude(pk=exclude).filter(email__iexact=data["email"]).exists():
                self.add_error("email", "البريد مستخدم لحساب آخر")
            phone = normalize_phone(data.get("phone"))
            if phone and User.objects.exclude(pk=exclude).filter(phone=phone).exists():
                self.add_error("phone", "رقم الجوال مستخدم لحساب آخر")
            data["phone"] = phone or None
            if not data.get("role"):
                self.add_error("role", "اختر الدور")
            if not self.user and not data.get("password"):
                self.add_error("password", "أدخل كلمة مرور مؤقتة للحساب الجديد")
            if data.get("password"):
                try:
                    validate_password(data["password"])
                except forms.ValidationError as e:
                    self.add_error("password", e)
        return data


class EmployeeImportForm(BootstrapMixin, forms.Form):
    file = forms.FileField(label="ملف Excel (.xlsx)")
    create_missing_units = forms.BooleanField(label="إنشاء الوحدات غير الموجودة تلقائيًا", required=False)
