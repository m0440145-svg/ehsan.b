"""اجتماع ← قرار ← تحويل إلى مهام ← إسناد ← تنفيذ ← اعتماد ← تحديث نسبة تنفيذ القرار."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.meetings.models import Meeting, MeetingDecision
from apps.notifications.models import Notification
from apps.tasks import selectors, services

from .base import PlatformTestCase


class DecisionToTaskTest(PlatformTestCase):
    def test_decision_converted_to_multiple_tasks_and_tracked(self):
        self.login(self.eda)
        resp = self.client.post(reverse("meetings:meetings"), {
            "number": "BM-01", "title": "اجتماع مجلس الإدارة", "committee": "مجلس الإدارة",
            "date": timezone.localdate().isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        meeting = Meeting.objects.get(number="BM-01")
        resp = self.client.post(reverse("meetings:decision_create"), {
            "number": "Q-100", "meeting": meeting.pk, "text": "إطلاق برنامج تدريبي",
            "decision_date": timezone.localdate().isoformat(), "followup_owner": self.eda_emp.pk,
        })
        decision = MeetingDecision.objects.get(number="Q-100")
        self.assertRedirects(resp, decision.get_absolute_url())

        due = (timezone.localdate() + timedelta(days=10)).isoformat()
        resp = self.client.post(reverse("meetings:convert", args=[decision.pk]), {
            "rows": 2,
            "title_0": "إعداد المحتوى", "unit_0": self.tech.pk, "owner_0": self.emp.pk, "participants_0": [self.emp2.pk],
            "due_date_0": due, "priority_0": "important",
            "title_1": "حجز القاعة", "unit_1": self.care.pk, "owner_1": "", "due_date_1": due, "priority_1": "normal",
        })
        self.assertRedirects(resp, decision.get_absolute_url())
        decision.refresh_from_db()
        tasks = list(decision.tasks.order_by("id"))
        self.assertEqual(len(tasks), 2)
        t1, t2 = tasks
        # نقل بيانات القرار تلقائيًا
        self.assertEqual(t1.source, "meeting_decision")
        self.assertIn("Q-100", t1.source_reference)
        self.assertIn("إطلاق برنامج تدريبي", t1.description)
        self.assertIn("مجلس الإدارة", t1.description)
        # الإسناد لوحدة دون موظف = رئيس الوحدة
        self.assertEqual(t2.owner, self.head2_emp)
        self.assertTrue(Notification.objects.filter(recipient=self.emp_user, task=t1, event="task_assigned").exists())
        self.assertEqual(decision.status, "in_progress")
        self.assertEqual(decision.implementation_pct, 0)

        # تنفيذ واعتماد المهمة الأولى
        services.update_progress(t1, user=self.emp_user, progress=100, comment="تم", done_work="المحتوى جاهز")
        decision.refresh_from_db()
        self.assertEqual(decision.implementation_pct, 45)  # 90% كحد أقصى قبل الاعتماد ÷ 2
        services.approve(t1, user=self.head, notes="معتمد")
        decision.refresh_from_db()
        self.assertEqual(decision.implementation_pct, 50)
        self.assertEqual(decision.status, "partial")

        # المهمة الثانية (رئيسة الوحدة هي المسؤولة) يعتمدها مساعد المدير التنفيذي
        services.update_progress(t2, user=self.head2, progress=100, comment="تم", done_work="تم الحجز")
        self.assertFalse(selectors.can_approve(self.head2, t2))  # لا يعتمد المسؤول إنجاز نفسه
        services.approve(t2, user=self.eda)
        decision.refresh_from_db()
        self.assertEqual(decision.implementation_pct, 100)
        self.assertEqual(decision.status, "implemented")

        resp = self.client.get(reverse("meetings:tracking"))
        self.assertContains(resp, "Q-100")
        resp = self.client.get(reverse("reports:report", args=["decision_impl"]))
        self.assertContains(resp, "100%")

    def test_convert_requires_owner_when_participants(self):
        self.login(self.eda)
        meeting = Meeting.objects.create(number="M-2", title="اجتماع", committee="لجنة", date=timezone.localdate())
        d = MeetingDecision.objects.create(number="Q-2", meeting=meeting, text="قرار")
        due = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.client.post(reverse("meetings:convert", args=[d.pk]), {
            "rows": 1, "title_0": "مهمة", "unit_0": self.tech.pk, "owner_0": "", "participants_0": [self.emp2.pk],
            "due_date_0": due, "priority_0": "normal",
        })
        self.assertEqual(d.tasks.count(), 0)

    def test_employee_cannot_manage_decisions(self):
        self.login(self.emp_user)
        self.assertEqual(self.client.get(reverse("meetings:decisions")).status_code, 403)
