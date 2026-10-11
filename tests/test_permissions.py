"""اختبار الصلاحيات (RBAC) ونطاق البيانات."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.tasks import selectors, services

from .base import PlatformTestCase


class PermissionsTest(PlatformTestCase):
    def setUp(self):
        super().setUp()
        self.t_tech = self.make_task(owner=self.emp, title="مهمة التقنية")
        self.t_care = self.make_task(owner=self.emp3, unit=self.care, title="مهمة الرعوية")
        self.t_secret = self.make_task(owner=self.emp3, unit=self.care, title="مهمة سرية", confidentiality="top_secret")

    def visible(self, user):
        return set(selectors.visible_tasks(user).values_list("title", flat=True))

    def test_employee_sees_only_own_tasks(self):
        self.assertEqual(self.visible(self.emp_user), {"مهمة التقنية"})
        self.assertEqual(self.visible(self.emp2_user), set())

    def test_unit_head_sees_unit_tasks(self):
        self.assertEqual(self.visible(self.head), {"مهمة التقنية"})
        self.assertEqual(self.visible(self.head2), {"مهمة الرعوية"})  # السرية للغاية لا تظهر لرئيس الوحدة

    def test_executive_sees_all_including_confidential(self):
        self.assertEqual(self.visible(self.ed), {"مهمة التقنية", "مهمة الرعوية", "مهمة سرية"})

    def test_viewer_read_only(self):
        self.assertNotIn("مهمة سرية", self.visible(self.viewer))
        self.assertIn("مهمة التقنية", self.visible(self.viewer))
        self.login(self.viewer)
        self.assertEqual(self.client.get(reverse("tasks:create")).status_code, 403)
        self.client.post(reverse("tasks:comment", args=[self.t_tech.pk]), {"body": "محاولة"})
        self.assertEqual(self.t_tech.comments.count(), 0)

    def test_pages_by_role(self):
        self.login(self.emp_user)
        self.assertEqual(self.client.get(reverse("tasks:detail", args=[self.t_care.pk])).status_code, 404)
        for name in ("organization:units", "accounts:users", "accounts:roles", "core:rules", "dashboard:executive", "tasks:all"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse("dashboard:employee"))
        self.login(self.head)
        self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse("dashboard:unit"))
        self.login(self.ed)
        self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse("dashboard:executive"))
        self.login(self.admin)
        self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse("dashboard:admin"))
        for name in ("organization:units", "accounts:users", "accounts:roles", "core:rules", "core:escalation_rules",
                     "core:notification_settings", "core:statuses", "core:priorities", "core:task_types", "core:audit"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_employee_cannot_approve_or_edit(self):
        services.update_progress(self.t_tech, user=self.emp_user, progress=100, comment="تم", done_work="تم")
        with self.assertRaises(PermissionDenied):
            services.approve(self.t_tech, user=self.emp_user)
        with self.assertRaises(PermissionDenied):
            services.approve(self.t_tech, user=self.head2)  # رئيس وحدة أخرى
        self.assertFalse(selectors.can_edit(self.emp_user, self.t_tech))

    def test_other_unit_employee_cannot_update(self):
        with self.assertRaises(PermissionDenied):
            services.update_progress(self.t_tech, user=self.emp3_user, progress=10, comment="x", done_work="x")

    def test_multi_assignee_requires_primary_owner(self):
        with self.assertRaises(ValidationError):
            services.create_task(user=self.ed, data={
                "title": "بدون مسؤول", "unit": self.tech, "owner": None,
                "due_date": self.t_tech.due_date}, participants=[self.emp, self.emp2])

    def test_unit_assignment_defaults_to_head(self):
        t = self.make_task(owner=None, title="مهمة للوحدة كاملة")
        self.assertEqual(t.owner, self.head_emp)

    def test_employee_role_cannot_create_tasks(self):
        with self.assertRaises(PermissionDenied):
            self.make_task(creator=self.emp_user)
