import re

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from apps.core.permissions import ROLES

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_phone(value):
    """توحيد رقم الجوال السعودي بصيغة 05XXXXXXXX."""
    if not value:
        return value
    v = re.sub(r"[\s\-()]", "", str(value).translate(_AR_DIGITS))
    if v.startswith("+966"):
        v = "0" + v[4:]
    elif v.startswith("00966"):
        v = "0" + v[5:]
    elif v.startswith("966") and len(v) == 12:
        v = "0" + v[3:]
    elif v.startswith("5") and len(v) == 9:
        v = "0" + v
    return v


class Permission(models.Model):
    code = models.CharField("الرمز", max_length=60, unique=True)
    name = models.CharField("الاسم", max_length=120)
    group = models.CharField("المجموعة", max_length=60)

    class Meta:
        db_table = "permissions"
        ordering = ["group", "code"]
        verbose_name = "صلاحية"

    def __str__(self):
        return self.name


class Role(models.Model):
    code = models.CharField("الرمز", max_length=40, unique=True, choices=ROLES)
    name = models.CharField("الاسم", max_length=80)
    description = models.TextField("الوصف", blank=True)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True, db_table="role_permissions")
    is_system = models.BooleanField(default=True)

    class Meta:
        db_table = "roles"
        verbose_name = "دور"

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("البريد الإلكتروني مطلوب")
        email = self.normalize_email(email).lower()
        if extra.get("phone"):
            extra["phone"] = normalize_phone(extra["phone"])
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("full_name", "مسؤول النظام")
        if "role" not in extra:
            extra["role"] = Role.objects.filter(code="admin").first()
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("البريد الإلكتروني", unique=True)
    phone = models.CharField("رقم الجوال", max_length=20, unique=True, null=True, blank=True)
    full_name = models.CharField("الاسم الكامل", max_length=150)
    role = models.ForeignKey(Role, verbose_name="الدور", on_delete=models.PROTECT, null=True, related_name="users")
    is_active = models.BooleanField("الحساب نشط", default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    otp_enabled = models.BooleanField("تفعيل التحقق الثنائي", default=False)
    must_change_password = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        verbose_name = "مستخدم"
        indexes = [models.Index(fields=["is_active"])]

    def __str__(self):
        return self.full_name or self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        self.phone = normalize_phone(self.phone) or None
        super().save(*args, **kwargs)

    @cached_property
    def permission_codes(self):
        if not self.role_id:
            return frozenset()
        return frozenset(self.role.permissions.values_list("code", flat=True))

    @property
    def role_code(self):
        return self.role.code if self.role_id else None

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def employee_or_none(self):
        return getattr(self, "employee", None)

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return (self.full_name or self.email).split(" ")[0]


class LoginAttempt(models.Model):
    identifier = models.CharField(max_length=190)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_attempts")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    success = models.BooleanField(default=False)
    reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "login_attempts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ip_address", "created_at"]),
            models.Index(fields=["identifier", "created_at"]),
        ]
