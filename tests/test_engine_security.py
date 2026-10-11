"""سير العمل، محرك القواعد، التصعيد، الأمان (الدخول، الملفات، سجل التدقيق)، وواجهة API."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LoginAttempt
from apps.audit.models import AuditLog
from apps.core.settings_service import get_rules, set_setting
from apps.tasks import services
from apps.tasks.engine import run_engine
from apps.tasks.models import Task, TaskEscalation
from apps.tasks.workflow import change_status

from .base import PASSWORD, PlatformTestCase


class WorkflowTest(PlatformTestCase):
    def test_invalid_transitions_rejected(self):
        t = self.make_task()
        with self.assertRaises(ValidationError):
            change_status(t, "closed", user=self.ed)  # لا إغلاق دون اعتماد
        with self.assertRaises(ValidationError):
            services.transition(t, user=self.emp_user, to="pending_approval")  # ليست يدوية
        with self.assertRaises(ValidationError):
            services.transition(t, user=self.emp_user, to="overdue")

    def test_returned_and_resubmitted(self):
        t = self.make_task()
        services.update_progress(t, user=self.emp_user, progress=100, comment="تم", done_work="تم")
        services.reject(t, user=self.head, notes="ناقص المرفقات")
        t.refresh_from_db()
        self.assertEqual(t.status, "returned")
        with self.assertRaises(ValidationError):
            services.reject(t, user=self.head, notes="")
        services.update_progress(t, user=self.emp_user, progress=100, comment="أرفقت", done_work="المرفقات")
        t.refresh_from_db()
        self.assertEqual(t.status, "pending_approval")

    def test_subtasks_auto_progress(self):
        t = self.make_task(auto_progress=True)
        s1 = services.add_subtask(t, user=self.head, title="أ", assignee=self.emp)
        s2 = services.add_subtask(t, user=self.head, title="ب", assignee=self.emp2)
        services.update_subtask(s1, user=self.emp_user, progress=100)
        t.refresh_from_db()
        self.assertEqual(t.progress, 50)
        services.update_subtask(s2, user=self.emp2_user, status="completed")
        t.refresh_from_db()
        self.assertEqual(t.progress, 100)
        self.assertEqual(t.status, "pending_approval")

    def test_db_enforces_single_primary_owner(self):
        from apps.tasks.models import TaskAssignee

        t = self.make_task()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskAssignee.objects.create(task=t, employee=self.emp2, role="primary")


class RuleEngineTest(PlatformTestCase):
    def test_overdue_flags_and_escalation_once(self):
        late = self.make_task(title="متأخرة", start_in=-20, due_in=-8)
        risk = self.make_task(title="مرشحة", start_in=-8, due_in=2)  # مر 80% والإنجاز 0
        stale = self.make_task(title="بدون تحديث", start_in=-3, due_in=30)
        Task.objects.filter(pk=stale.pk).update(last_activity_at=timezone.now() - timedelta(days=6))
        run_engine()
        late.refresh_from_db(); risk.refresh_from_db(); stale.refresh_from_db()
        self.assertEqual(late.status, "overdue")
        self.assertEqual(late.escalation_level, 3)  # تجاوز 7 أيام => المدير التنفيذي
        self.assertTrue(risk.flag_needs_followup and risk.flag_at_risk)
        self.assertTrue(stale.flag_stale)
        count = TaskEscalation.objects.filter(task=late).count()
        run_engine()
        self.assertEqual(TaskEscalation.objects.filter(task=late).count(), count)  # لا تكرار
        self.assertTrue(late.notifications.filter(recipient=self.ed, event="escalation").exists())
        # تمديد الموعد يعيد المهمة قيد التنفيذ
        services.update_task(late, user=self.ed, data={"due_date": timezone.localdate() + timedelta(days=5)})
        late.refresh_from_db()
        self.assertEqual(late.status, "in_progress")

    def test_rules_are_configurable(self):
        rules = get_rules()
        rules["auto_overdue"] = False
        set_setting("rules", rules)
        t = self.make_task(start_in=-10, due_in=-1)
        run_engine()
        t.refresh_from_db()
        self.assertEqual(t.status, "assigned")

    def test_obstacle_sets_stalled_and_resolution_restores(self):
        t = self.make_task()
        services.update_progress(t, user=self.emp_user, progress=20, comment="بدء", done_work="بدء")
        ob = services.register_obstacle(t, user=self.emp_user, data={"obstacle_type": "financial", "description": "اعتماد",
                                                                      "needs_admin_decision": True})
        t.refresh_from_db()
        self.assertEqual(t.status, "stalled")
        self.assertTrue(t.needs_ed_decision)
        services.resolve_obstacle(ob, user=self.emp_user)
        t.refresh_from_db()
        self.assertEqual(t.status, "in_progress")
        self.assertFalse(t.needs_ed_decision)


@override_settings(LOGIN_MAX_ATTEMPTS=3)
class SecurityTest(PlatformTestCase):
    def test_login_with_email_and_phone(self):
        r = self.client.post(reverse("accounts:login"), {"identifier": "ahmad@test.local", "password": PASSWORD})
        self.assertRedirects(r, reverse("dashboard:home"), fetch_redirect_response=False)
        self.client.logout()
        r = self.client.post(reverse("accounts:login"), {"identifier": "+966511000005", "password": PASSWORD})
        self.assertRedirects(r, reverse("dashboard:home"), fetch_redirect_response=False)
        self.assertEqual(LoginAttempt.objects.filter(success=True).count(), 2)

    def test_lockout_after_failed_attempts(self):
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"identifier": "ahmad@test.local", "password": "wrong"})
        self.emp_user.refresh_from_db()
        self.assertTrue(self.emp_user.is_locked)
        r = self.client.post(reverse("accounts:login"), {"identifier": "ahmad@test.local", "password": PASSWORD})
        self.assertContains(r, "مقفل مؤقتًا")
        self.assertEqual(LoginAttempt.objects.filter(success=False).count(), 4)

    def test_csrf_enforced(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        r = c.post(reverse("accounts:login"), {"identifier": "ahmad@test.local", "password": PASSWORD})
        self.assertEqual(r.status_code, 403)

    def test_upload_validation(self):
        t = self.make_task()
        with self.assertRaises(ValidationError):
            services.add_attachment(t, self.emp_user, SimpleUploadedFile("virus.exe", b"MZ\x90\x00"))
        with self.assertRaises(ValidationError):
            services.add_attachment(t, self.emp_user, SimpleUploadedFile("fake.pdf", b"MZ\x90\x00not a pdf"))

    def test_attachment_download_protected(self):
        from .base import pdf_file

        t = self.make_task()
        att = services.add_attachment(t, self.emp_user, pdf_file())
        self.login(self.emp3_user)
        self.assertEqual(self.client.get(reverse("tasks:attachment", args=[att.pk])).status_code, 404)

    def test_audit_log_immutable(self):
        t = self.make_task()
        entry = AuditLog.objects.filter(task=t).first()
        with self.assertRaises(PermissionError):
            entry.description = "تلاعب"
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.filter(task=t).delete()

    def test_api_token_and_scoping(self):
        self.make_task(title="مهمتي")
        self.make_task(owner=self.emp3, unit=self.care, title="ليست لي")
        r = self.client.post("/api/v1/auth/token/", {"identifier": "ahmad@test.local", "password": PASSWORD})
        token = r.json()["token"]
        r = self.client.get("/api/v1/tasks/", HTTP_AUTHORIZATION=f"Token {token}")
        titles = [t["title"] for t in r.json()["results"]]
        self.assertEqual(titles, ["مهمتي"])
        r = self.client.get("/api/v1/dashboard/kpis/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.json()["kpis"]["total"], 1)
        self.assertEqual(self.client.get("/api/v1/tasks/").status_code, 403)

    def test_api_progress_and_approval_flow(self):
        from rest_framework.authtoken.models import Token

        t = self.make_task()
        emp_auth = {"HTTP_AUTHORIZATION": f"Token {Token.objects.create(user=self.emp_user).key}"}
        head_auth = {"HTTP_AUTHORIZATION": f"Token {Token.objects.create(user=self.head).key}"}
        r = self.client.post(f"/api/v1/tasks/{t.pk}/progress/", {"progress": 100, "comment": "تم", "done_work": "تم"},
                             content_type="application/json", **emp_auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "pending_approval")
        r = self.client.post(f"/api/v1/tasks/{t.pk}/approve/", {}, content_type="application/json", **emp_auth)
        self.assertEqual(r.status_code, 403)
        r = self.client.post(f"/api/v1/tasks/{t.pk}/approve/", {"notes": "ok"}, content_type="application/json", **head_auth)
        self.assertEqual(r.json()["status"], "closed")
