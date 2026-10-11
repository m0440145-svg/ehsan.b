from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.organization.models import Employee

from .models import Role, User, normalize_phone


class LoginForm(forms.Form):
    identifier = forms.CharField(
        label="البريد الإلكتروني أو رقم الجوال",
        max_length=190,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True, "dir": "ltr"}),
    )
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class OTPForm(forms.Form):
    code = forms.CharField(label="رمز التحقق", max_length=6, min_length=6, widget=forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric"}))


class UserForm(forms.ModelForm):
    password = forms.CharField(
        label="كلمة المرور", required=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="اتركها فارغة للإبقاء على كلمة المرور الحالية",
    )
    employee = forms.ModelChoiceField(
        label="ربط بموظف", queryset=Employee.objects.none(), required=False,
        help_text="ربط الحساب بملف موظف لإسناد المهام إليه",
    )

    class Meta:
        model = User
        fields = ["full_name", "email", "phone", "role", "is_active", "otp_enabled", "must_change_password"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = getattr(self.instance, "employee", None) if self.instance.pk else None
        qs = Employee.objects.filter(user__isnull=True)
        if current:
            qs = Employee.objects.filter(pk=current.pk) | qs
            self.fields["employee"].initial = current
        self.fields["employee"].queryset = qs.order_by("full_name")
        self.fields["role"].queryset = Role.objects.all()
        if not self.instance.pk:
            self.fields["password"].required = True
            self.fields["password"].help_text = ""

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if phone and User.objects.exclude(pk=self.instance.pk).filter(phone=phone).exists():
            raise forms.ValidationError("رقم الجوال مستخدم لحساب آخر")
        return phone or None

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.exclude(pk=self.instance.pk).filter(email=email).exists():
            raise forms.ValidationError("البريد الإلكتروني مستخدم لحساب آخر")
        return email

    def clean_password(self):
        pw = self.cleaned_data.get("password")
        if pw:
            validate_password(pw, self.instance)
        return pw


class ProfilePasswordForm(forms.Form):
    current_password = forms.CharField(label="كلمة المرور الحالية", widget=forms.PasswordInput)
    new_password = forms.CharField(label="كلمة المرور الجديدة", widget=forms.PasswordInput)
    confirm_password = forms.CharField(label="تأكيد كلمة المرور", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        if not self.user.check_password(self.cleaned_data["current_password"]):
            raise forms.ValidationError("كلمة المرور الحالية غير صحيحة")
        return self.cleaned_data["current_password"]

    def clean(self):
        data = super().clean()
        if data.get("new_password") and data.get("new_password") != data.get("confirm_password"):
            self.add_error("confirm_password", "كلمتا المرور غير متطابقتين")
        elif data.get("new_password"):
            validate_password(data["new_password"], self.user)
        return data
