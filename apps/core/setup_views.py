"""
معالج الإعداد الأول: يظهر فقط عندما لا يوجد أي مستخدم في النظام.
ينشئ: البيانات المرجعية (الأدوار/الصلاحيات/قواعد التصعيد)، بيانات الجهة، حساب مسؤول النظام الأول،
والوحدات التنظيمية الافتراضية اختياريًا.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render

from apps.accounts.models import Role, User, normalize_phone
from apps.audit import services as audit
from apps.organization.models import Employee, EmployeeUnit, Unit

from .bootstrap import create_default_units, ensure_reference_data
from .branding import save_org
from .forms import BootstrapMixin


def setup_required():
    return not User.objects.exists()


class SetupForm(BootstrapMixin, forms.Form):
    org_name = forms.CharField(label="اسم الجهة الرسمي", max_length=200, initial="جمعية الإحسان للخدمات الاجتماعية ببريدة")
    org_short = forms.CharField(label="الاسم المختصر", max_length=100, initial="جمعية الإحسان")
    city = forms.CharField(label="المدينة", max_length=80, required=False, initial="بريدة")
    org_phone = forms.CharField(label="هاتف الجهة", max_length=30, required=False)
    org_email = forms.EmailField(label="بريد الجهة", required=False)
    logo = forms.FileField(label="شعار الجهة (اختياري)", required=False)
    create_units = forms.BooleanField(label="إنشاء الوحدات التنظيمية الافتراضية للجمعية (16 وحدة، يمكن تعديلها لاحقًا)",
                                      required=False, initial=True)

    full_name = forms.CharField(label="اسم مسؤول النظام", max_length=150)
    email = forms.EmailField(label="البريد الإلكتروني للدخول")
    phone = forms.CharField(label="رقم الجوال", max_length=20, required=False)
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="تأكيد كلمة المرور", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    is_employee = forms.BooleanField(label="مسؤول النظام موظف في الجمعية (يمكن إسناد المهام إليه)", required=False)
    employee_no = forms.CharField(label="رقم الموظف", max_length=30, required=False)
    job_title = forms.CharField(label="المسمى الوظيفي", max_length=150, required=False)

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password") != data.get("password2"):
            self.add_error("password2", "كلمتا المرور غير متطابقتين")
        elif data.get("password"):
            try:
                validate_password(data["password"], User(email=data.get("email", ""), full_name=data.get("full_name", "")))
            except forms.ValidationError as e:
                self.add_error("password", e)
        if data.get("is_employee") and not data.get("employee_no"):
            self.add_error("employee_no", "رقم الموظف مطلوب")
        if data.get("phone"):
            data["phone"] = normalize_phone(data["phone"])
        return data


def setup_view(request):
    if not setup_required():
        raise Http404
    form = SetupForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                ensure_reference_data()
                admin_role = Role.objects.get(code="admin")
                user = User.objects.create_superuser(d["email"], d["password"], full_name=d["full_name"],
                                                     phone=d["phone"] or None, role=admin_role)
                save_org({"name": d["org_name"], "short_name": d["org_short"], "city": d["city"],
                          "phone": d["org_phone"], "email": d["org_email"], "setup_completed": True},
                         user=user, logo=d.get("logo"))
                units = create_default_units() if d["create_units"] else 0
                if d["is_employee"]:
                    emp = Employee.objects.create(user=user, employee_no=d["employee_no"], full_name=d["full_name"],
                                                  job_title=d["job_title"] or "مسؤول النظام")
                    unit = Unit.objects.filter(code="TECH").first()
                    if unit:
                        EmployeeUnit.objects.create(employee=emp, unit=unit)
                audit.log("user.created", user=user, obj=user, description=f"إعداد المنصة: إنشاء مسؤول النظام الأول ({units} وحدة)")
        except forms.ValidationError as e:
            form.add_error(None, e)
        else:
            login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
            messages.success(request, "تم إعداد المنصة بنجاح. الخطوة التالية: أضف الموظفين وحساباتهم.")
            return redirect("core:getting_started")
    return render(request, "core/setup.html", {"form": form})
