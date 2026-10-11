from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.files import secure_upload_path


class Unit(models.Model):
    name = models.CharField("اسم الوحدة", max_length=150, unique=True)
    code = models.CharField("الرمز", max_length=30, unique=True, null=True, blank=True)
    description = models.TextField("وصف الوحدة", blank=True)
    head = models.ForeignKey(
        "organization.Employee", verbose_name="رئيس الوحدة", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="headed_units",
    )
    parent = models.ForeignKey("self", verbose_name="تتبع لـ", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    is_active = models.BooleanField("الوحدة نشطة", default=True)
    established_on = models.DateField("تاريخ الإنشاء", default=timezone.localdate)
    sort_order = models.PositiveSmallIntegerField("الترتيب", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "units"
        ordering = ["sort_order", "name"]
        verbose_name = "وحدة تنظيمية"

    def __str__(self):
        return self.name


class Employee(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "على رأس العمل"
        LEAVE = "leave", "في إجازة"
        INACTIVE = "inactive", "غير نشط"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="حساب المستخدم", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="employee",
    )
    employee_no = models.CharField("رقم الموظف", max_length=30, unique=True)
    full_name = models.CharField("الاسم", max_length=150)
    job_title = models.CharField("المسمى الوظيفي", max_length=150, blank=True)
    manager = models.ForeignKey("self", verbose_name="المدير المباشر", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports")
    units = models.ManyToManyField(Unit, through="EmployeeUnit", related_name="employees", verbose_name="الوحدات")
    join_date = models.DateField("تاريخ الانضمام", null=True, blank=True)
    photo = models.FileField("صورة", upload_to=secure_upload_path, null=True, blank=True)
    status = models.CharField("الحالة", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "employees"
        ordering = ["full_name"]
        verbose_name = "موظف"
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return self.full_name

    @property
    def primary_unit(self):
        link = self.unit_links.select_related("unit").order_by("-is_primary", "id").first()
        return link.unit if link else None

    @property
    def email(self):
        return self.user.email if self.user_id else ""

    @property
    def phone(self):
        return self.user.phone if self.user_id else ""

    @property
    def initials(self):
        parts = self.full_name.split()
        return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")) if parts else "؟"


class EmployeeUnit(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="unit_links")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="employee_links")
    is_primary = models.BooleanField("الوحدة الأساسية", default=True)

    class Meta:
        db_table = "employee_units"
        constraints = [models.UniqueConstraint(fields=["employee", "unit"], name="uniq_employee_unit")]
