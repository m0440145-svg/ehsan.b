"""الإعداد الأول، بيانات الجهة، إضافة موظف بحسابه، الاستيراد من Excel، وإلزام تغيير كلمة المرور المؤقتة."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import Role, User
from apps.core.branding import get_org
from apps.organization.models import Employee, Unit
from apps.organization.services import COLUMNS

from .base import PASSWORD, TMP_MEDIA, PlatformTestCase

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@override_settings(MEDIA_ROOT=TMP_MEDIA, TASK_ENGINE_AUTORUN=False)
class FirstRunSetupTest(TestCase):
    def test_setup_wizard_creates_admin_org_and_units(self):
        self.assertRedirects(self.client.get(reverse("accounts:login")), reverse("setup"))
        r = self.client.post(reverse("setup"), {
            "org_name": "جمعية الإحسان للخدمات الاجتماعية ببريدة", "org_short": "جمعية الإحسان", "city": "بريدة",
            "org_phone": "0163000000", "org_email": "info@example.org",
            "logo": SimpleUploadedFile("logo.png", PNG, content_type="image/png"), "create_units": "on",
            "full_name": "مسؤول المنصة", "email": "it@example.org", "phone": "0555555555",
            "password": PASSWORD, "password2": PASSWORD, "is_employee": "on", "employee_no": "EH-1", "job_title": "مسؤول التقنية",
        })
        self.assertRedirects(r, reverse("core:getting_started"))
        admin = User.objects.get(email="it@example.org")
        self.assertEqual(admin.role.code, "admin")
        self.assertTrue(admin.is_superuser)
        self.assertEqual(Unit.objects.count(), 16)
        self.assertEqual(admin.employee.employee_no, "EH-1")
        org = get_org()
        self.assertEqual(org["short_name"], "جمعية الإحسان")
        self.assertTrue(org["logo"])
        self.assertEqual(self.client.get(reverse("branding_logo")).status_code, 200)
        # لا يمكن الوصول للمعالج مرة أخرى
        self.client.logout()
        self.assertEqual(self.client.get(reverse("setup")).status_code, 404)


class OnboardingTest(PlatformTestCase):
    def test_org_settings_update(self):
        self.login(self.admin)
        r = self.client.post(reverse("core:organization"), {"name": "جهة تجريبية", "short_name": "تجريبية", "city": "بريدة"})
        self.assertRedirects(r, reverse("core:organization"))
        self.assertContains(self.client.get(reverse("dashboard:admin")), "تجريبية")

    def test_add_employee_with_account_then_forced_password_change(self):
        self.login(self.admin)
        r = self.client.post(reverse("organization:employee_create"), {
            "full_name": "سعد بن علي", "employee_no": "N-77", "job_title": "محاسب", "status": "active",
            "primary_unit": self.care.pk, "units": [self.care.pk], "is_unit_head": "",
            "has_account": "on", "email": "saad@test.local", "phone": "0577777777",
            "role": Role.objects.get(code="employee").pk, "password": "Temp@Pass2026", "account_active": "on",
        })
        emp = Employee.objects.get(employee_no="N-77")
        self.assertRedirects(r, reverse("organization:employee_detail", args=[emp.pk]))
        self.assertTrue(emp.user.must_change_password)
        self.assertEqual(emp.primary_unit, self.care)
        # أول دخول: يُوجَّه لتغيير كلمة المرور
        self.client.logout()
        self.client.post(reverse("accounts:login"), {"identifier": "0577777777", "password": "Temp@Pass2026"})
        self.assertRedirects(self.client.get(reverse("dashboard:employee")), reverse("accounts:profile"))
        self.client.post(reverse("accounts:profile"), {"current_password": "Temp@Pass2026",
                                                       "new_password": "New@Secure2026", "confirm_password": "New@Secure2026"})
        self.assertEqual(self.client.get(reverse("dashboard:employee")).status_code, 200)

    def test_add_second_admin(self):
        self.login(self.admin)
        r = self.client.post(reverse("accounts:user_create"), {
            "full_name": "مسؤول ثانٍ", "email": "admin2@test.local", "role": Role.objects.get(code="admin").pk,
            "password": "Admin2@Secure", "is_active": "on", "must_change_password": "on"})
        self.assertRedirects(r, reverse("accounts:users"))
        self.assertEqual(User.objects.get(email="admin2@test.local").role.code, "admin")

    def _xlsx(self, rows):
        wb = Workbook()
        ws = wb.active
        ws.append([label for _, label in COLUMNS])
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile("emps.xlsx", buf.getvalue())

    def test_excel_import(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("organization:employee_import_template")).status_code, 200)
        f = self._xlsx([
            ["نورة الحربي", "X-1", "رئيسة", "CARE", "", "نعم", "", "noura@test.local", "0588888881", "رئيس الوحدة", "2024-02-01", ""],
            ["ليلى السبيعي", "X-2", "أخصائية", "وحدة الخدمات الرعوية", "TECH", "لا", "X-1", "laila@test.local", "", "", "", ""],
            ["عامل بلا حساب", "X-3", "سائق", "TECH", "", "", "", "", "", "", "", ""],
        ])
        r = self.client.post(reverse("organization:employee_import"), {"file": f})
        self.assertContains(r, "تم استيراد 3 موظف")
        noura = Employee.objects.get(employee_no="X-1")
        laila = Employee.objects.get(employee_no="X-2")
        self.assertEqual(noura.user.role.code, "unit_head")
        self.care.refresh_from_db()
        self.assertEqual(self.care.head, noura)
        self.assertEqual(laila.manager, noura)
        self.assertEqual(laila.units.count(), 2)
        self.assertTrue(laila.user.must_change_password)
        self.assertIsNone(Employee.objects.get(employee_no="X-3").user)

    def test_excel_import_rejects_whole_file_on_error(self):
        self.login(self.admin)
        f = self._xlsx([
            ["صحيح", "Y-1", "", "TECH", "", "", "", "", "", "", "", ""],
            ["خطأ", "Y-2", "", "وحدة غير موجودة", "", "", "", "ahmad@test.local", "", "", "", ""],
        ])
        r = self.client.post(reverse("organization:employee_import"), {"file": f})
        self.assertContains(r, "غير موجودة")
        self.assertContains(r, "مستخدم")
        self.assertFalse(Employee.objects.filter(employee_no__startswith="Y-").exists())
