import shutil
import tempfile
from datetime import timedelta

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.bootstrap import ensure_reference_data
from apps.organization.models import Employee, EmployeeUnit, Unit

PASSWORD = "Test@Pass2026"
TMP_MEDIA = tempfile.mkdtemp(prefix="ehsan-test-media-")

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def pdf_file(name="report.pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


@override_settings(MEDIA_ROOT=TMP_MEDIA, TASK_ENGINE_AUTORUN=False)
class PlatformTestCase(TestCase):
    """بيئة اختبار مصغرة: وحدتان، مدير تنفيذي، مساعد، رئيسا وحدتين، موظفون، مستخدم عرض، مسؤول نظام."""

    @classmethod
    def setUpTestData(cls):
        ensure_reference_data()
        roles = {r.code: r for r in Role.objects.all()}
        cls.tech = Unit.objects.create(name="وحدة التقنية والتحول الرقمي", code="TECH")
        cls.care = Unit.objects.create(name="وحدة الخدمات الرعوية", code="CARE")

        def person(key, name, role, unit, phone):
            u = User.objects.create_user(f"{key}@test.local", PASSWORD, full_name=name, phone=phone, role=roles[role])
            e = Employee.objects.create(user=u, employee_no=f"T-{phone[-3:]}", full_name=name, job_title=role)
            if unit:
                EmployeeUnit.objects.create(employee=e, unit=unit)
            return u, e

        cls.ed, cls.ed_emp = person("ed", "المدير التنفيذي", "executive_director", None, "0511000001")
        cls.eda, cls.eda_emp = person("eda", "مساعد المدير", "ed_assistant", None, "0511000002")
        cls.head, cls.head_emp = person("fahad", "فهد رئيس التقنية", "unit_head", cls.tech, "0511000003")
        cls.head2, cls.head2_emp = person("sara", "سارة رئيسة الرعوية", "unit_head", cls.care, "0511000004")
        cls.emp_user, cls.emp = person("ahmad", "أحمد الموظف", "employee", cls.tech, "0511000005")
        cls.emp2_user, cls.emp2 = person("mohammed", "محمد المشارك", "employee", cls.tech, "0511000006")
        cls.emp3_user, cls.emp3 = person("amal", "أمل الرعوية", "employee", cls.care, "0511000007")
        cls.viewer, _ = person("viewer", "مستخدم العرض", "viewer", None, "0511000008")
        cls.admin = User.objects.create_superuser("admin@test.local", PASSWORD, role=roles["admin"])
        Unit.objects.filter(pk=cls.tech.pk).update(head=cls.head_emp)
        Unit.objects.filter(pk=cls.care.pk).update(head=cls.head2_emp)
        Employee.objects.filter(pk__in=[cls.emp.pk, cls.emp2.pk]).update(manager=cls.head_emp)
        cls.tech.refresh_from_db()
        cls.care.refresh_from_db()

    def setUp(self):
        cache.clear()
        for attr in ("ed", "eda", "head", "head2", "emp_user", "emp2_user", "emp3_user", "viewer", "admin"):
            getattr(self, attr).refresh_from_db()
            getattr(self, attr).__dict__.pop("permission_codes", None)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def login(self, user):
        self.client.logout()
        ok = self.client.login(username=user.email, password=PASSWORD)
        self.assertTrue(ok, f"فشل تسجيل دخول {user.email}")

    _DEFAULT = object()

    def make_task(self, owner=_DEFAULT, participants=(), unit=None, due_in=10, start_in=-2, creator=None, **extra):
        from apps.tasks import services

        data = {
            "title": extra.pop("title", "مهمة اختبار"),
            "description": "وصف",
            "unit": unit or self.tech,
            "owner": self.emp if owner is self._DEFAULT else owner,
            "start_date": timezone.localdate() + timedelta(days=start_in),
            "due_date": timezone.localdate() + timedelta(days=due_in),
            **extra,
        }
        return services.create_task(user=creator or self.ed, data=data, participants=list(participants))
