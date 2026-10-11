"""
السيناريو الإلزامي من البداية حتى الإغلاق، عبر واجهات الويب الفعلية (طلبات HTTP مع CSRF):
1 المدير ينشئ مهمة ← 2 يسندها لمسؤول رئيسي ومشاركين ← 3 يصل التنبيه للجميع ← 4 الموظف يفتح المهمة
← 5 يحدّث الإنجاز ← 6 يرفع ملفًا ← 7 يسجل عائقًا ← 8 يصل العائق لرئيس الوحدة ← 9 رئيس الوحدة يرد
← 10 الموظف يكمل ← 11 يرفع الإنجاز 100% ← 12 بانتظار الاعتماد ← 13 رئيس الوحدة يعتمد ← 14 تغلق
← 15 يظهر في لوحات التحكم والتقارير ← 16 يحتفظ النظام بكامل سجل النشاط.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.tasks.models import Task, TaskAttachment, TaskObstacle, TaskStatusHistory, TaskUpdate

from .base import PlatformTestCase, pdf_file


class FullTaskLifecycleTest(PlatformTestCase):
    def test_full_lifecycle_via_web(self):
        due = timezone.localdate() + timedelta(days=7)

        # 1-2: المدير التنفيذي ينشئ المهمة ويسندها لمسؤول رئيسي ومشاركين
        self.login(self.ed)
        resp = self.client.post(reverse("tasks:create"), {
            "title": "إعداد تقرير الأداء الربعي", "description": "تقرير شامل لأداء الربع الثالث",
            "source": "ed_assignment", "unit": self.tech.pk, "owner": self.emp.pk,
            "participants": [self.emp2.pk], "participant_units": [self.care.pk],
            "start_date": timezone.localdate().isoformat(), "due_date": due.isoformat(),
            "priority": "important", "confidentiality": "normal", "progress": 0,
            "requires_approval": "on", "expected_result": "تقرير معتمد", "success_indicator": "اعتماد التقرير",
        })
        task = Task.objects.get(title="إعداد تقرير الأداء الربعي")
        self.assertRedirects(resp, task.get_absolute_url())
        self.assertEqual(task.status, "assigned")
        self.assertEqual(task.owner, self.emp)
        self.assertEqual({e.pk for e in task.participants}, {self.emp2.pk})
        self.assertEqual([u.pk for u in task.participant_units], [self.care.pk])

        # 3: يصل التنبيه للجميع (المسؤول، المشارك، رئيس الوحدة المشاركة)
        self.assertTrue(Notification.objects.filter(recipient=self.emp_user, task=task, event="task_assigned").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.emp2_user, task=task, event="task_participant").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.head2, task=task, event="task_participant").exists())

        # 4: الموظف يفتح المهمة (ومن ليس له علاقة لا يراها)
        self.login(self.emp_user)
        self.assertEqual(self.client.get(task.get_absolute_url()).status_code, 200)

        # 5: تحديث نسبة الإنجاز مع التعليق والأعمال المنجزة والمتبقية والتاريخ
        resp = self.client.post(reverse("tasks:progress", args=[task.pk]), {
            "progress": 40, "comment": "تم جمع البيانات", "done_work": "جمع بيانات 5 وحدات",
            "remaining_work": "التحليل والصياغة", "update_date": timezone.localdate().isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.progress, 40)
        self.assertEqual(task.status, "in_progress")

        # 6: رفع ملف
        resp = self.client.post(reverse("tasks:upload", args=[task.pk]), {"attachments": [pdf_file("بيانات.pdf")]})
        self.assertEqual(resp.status_code, 302)
        att = TaskAttachment.objects.get(task=task)
        self.assertEqual(att.kind, "pdf")
        self.assertEqual(self.client.get(reverse("tasks:attachment", args=[att.pk])).status_code, 200)

        # 7: تسجيل عائق
        resp = self.client.post(reverse("tasks:obstacle", args=[task.pk]), {
            "obstacle_type": "missing_info", "description": "لم تصل بيانات وحدة الخدمات الرعوية",
            "cause_party": "وحدة الخدمات الرعوية", "required_action": "التوجيه بتزويدنا بالبيانات",
            "intervener": self.head_emp.pk, "expected_resolution_date": due.isoformat(), "impact": "high",
        })
        self.assertEqual(resp.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, "stalled")
        obstacle = TaskObstacle.objects.get(task=task)

        # 8: وصول العائق لرئيس الوحدة
        self.assertTrue(Notification.objects.filter(recipient=self.head, task=task, event="obstacle_registered").exists())

        # 9: رئيس الوحدة يرد ويعالج العائق
        self.login(self.head)
        resp = self.client.post(reverse("tasks:obstacle_respond", args=[task.pk, obstacle.pk]),
                                {"response": "تم التنسيق، ستصلك البيانات اليوم", "resolve": "on"})
        self.assertEqual(resp.status_code, 302)
        obstacle.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(obstacle.status, "resolved")
        self.assertEqual(task.status, "in_progress")
        self.assertTrue(Notification.objects.filter(recipient=self.emp_user, task=task, event="obstacle_responded").exists())

        # 10-11: الموظف يكمل ويرفع الإنجاز إلى 100%
        self.login(self.emp_user)
        self.client.post(reverse("tasks:comment", args=[task.pk]), {"body": "@[فهد رئيس التقنية] استلمت البيانات، شكرًا"})
        self.assertTrue(Notification.objects.filter(recipient=self.head, task=task, event="mentioned").exists())
        resp = self.client.post(reverse("tasks:progress", args=[task.pk]), {
            "progress": 100, "comment": "اكتمل التقرير", "done_work": "التحليل والصياغة النهائية",
            "update_date": timezone.localdate().isoformat(),
        })
        task.refresh_from_db()

        # 12: لا تُغلق مباشرة بل تنتقل إلى بانتظار الاعتماد ويُطلب الاعتماد
        self.assertEqual(task.status, "pending_approval")
        self.assertTrue(Notification.objects.filter(recipient=self.head, task=task, event="approval_requested").exists())
        # الموظف لا يستطيع اعتماد مهمته
        self.client.post(reverse("tasks:approve", args=[task.pk]), {"notes": ""})
        task.refresh_from_db()
        self.assertEqual(task.status, "pending_approval")

        # 13-14: رئيس الوحدة يعتمد فتُغلق
        self.login(self.head)
        resp = self.client.post(reverse("tasks:approve", args=[task.pk]), {"notes": "عمل ممتاز"})
        self.assertEqual(resp.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, "closed")
        self.assertEqual(task.approved_by, self.head)
        self.assertIsNotNone(task.closed_at)
        self.assertTrue(Notification.objects.filter(recipient=self.emp_user, task=task, event="task_closed").exists())

        # 15: يظهر في لوحة التحكم والتقارير
        self.login(self.ed)
        resp = self.client.get(reverse("dashboard:executive"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["kpis"]["done"], 1)
        self.assertEqual(resp.context["kpis"]["on_time_rate"], 100.0)
        resp = self.client.get(reverse("reports:report", args=["completed"]))
        self.assertContains(resp, task.number)
        resp = self.client.get(reverse("reports:report", args=["units"]) + "?export=xlsx")
        self.assertEqual(resp["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.login(self.head)
        resp = self.client.get(reverse("dashboard:unit"))
        self.assertEqual(resp.context["kpis"]["done"], 1)

        # 16: سجل النشاط الكامل
        actions = set(AuditLog.objects.filter(task=task).values_list("action", flat=True))
        for required in ["task.created", "task.status_changed", "task.progress_changed", "task.file_uploaded",
                         "task.obstacle_registered", "task.obstacle_responded", "task.comment_added",
                         "task.approval_requested", "task.approved", "task.closed"]:
            self.assertIn(required, actions)
        path = list(TaskStatusHistory.objects.filter(task=task).order_by("id").values_list("to_status", flat=True))
        self.assertEqual(path, ["new", "assigned", "in_progress", "stalled", "in_progress", "pending_approval", "closed"])
        self.assertEqual(TaskUpdate.objects.filter(task=task).count(), 2)
        resp = self.client.get(task.get_absolute_url() + "?tab=activity")
        self.assertContains(resp, "اعتماد المهمة")
