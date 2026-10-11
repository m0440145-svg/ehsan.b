from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.files import secure_upload_path

from .constants import (
    ACTIVE_STATUSES,
    DONE_STATUSES,
    PRIORITY_STYLE,
    STATUS_STYLE,
    TERMINAL_STATUSES,
    AssigneeRole,
    Confidentiality,
    EscalationTarget,
    Impact,
    ObstacleStatus,
    ObstacleType,
    Priority,
    Source,
    Status,
    SubtaskStatus,
    UnitRole,
)


class TaskType(models.Model):
    name = models.CharField("نوع المهمة", max_length=100, unique=True)
    description = models.CharField("الوصف", max_length=250, blank=True)
    is_active = models.BooleanField("نشط", default=True)

    class Meta:
        db_table = "task_types"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Task(models.Model):
    number = models.CharField("رقم المهمة", max_length=20, unique=True, null=True, blank=True)
    title = models.CharField("عنوان المهمة", max_length=250)
    description = models.TextField("وصف المهمة", blank=True)
    source = models.CharField("مصدر المهمة", max_length=30, choices=Source.choices, default=Source.STANDALONE)
    source_reference = models.CharField("مرجع المصدر", max_length=120, blank=True,
                                        help_text="رقم المراسلة أو الخطة أو المرجع الخارجي")
    task_type = models.ForeignKey(TaskType, verbose_name="نوع المهمة", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    project = models.CharField("المشروع", max_length=150, blank=True)
    unit = models.ForeignKey("organization.Unit", verbose_name="الوحدة المسؤولة", on_delete=models.PROTECT, related_name="tasks")
    owner = models.ForeignKey("organization.Employee", verbose_name="المسؤول الرئيسي", on_delete=models.PROTECT, related_name="owned_tasks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="أنشأها", null=True, on_delete=models.SET_NULL, related_name="created_tasks")
    start_date = models.DateField("تاريخ البدء", default=timezone.localdate)
    due_date = models.DateField("تاريخ الاستحقاق")
    priority = models.CharField("الأولوية", max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    confidentiality = models.CharField("مستوى السرية", max_length=20, choices=Confidentiality.choices, default=Confidentiality.NORMAL)
    status = models.CharField("الحالة", max_length=20, choices=Status.choices, default=Status.NEW)
    progress = models.PositiveSmallIntegerField("نسبة الإنجاز", default=0)
    expected_result = models.TextField("النتيجة المطلوبة", blank=True)
    success_indicator = models.CharField("مؤشر النجاح", max_length=250, blank=True)
    notes = models.TextField("ملاحظات", blank=True)
    requires_approval = models.BooleanField("يتطلب اعتماد الإنجاز", default=True)
    auto_progress = models.BooleanField("احتساب الإنجاز من المهام الفرعية", default=False)

    # مؤشرات محرك القواعد
    flag_needs_followup = models.BooleanField("بحاجة متابعة", default=False)
    flag_at_risk = models.BooleanField("مرشحة للتعثر", default=False)
    flag_stale = models.BooleanField("بدون تحديث", default=False)
    escalation_level = models.PositiveSmallIntegerField("مستوى التصعيد", default=0)
    needs_ed_decision = models.BooleanField("تتطلب قرار المدير التنفيذي", default=False)

    last_activity_at = models.DateTimeField("آخر تحديث", default=timezone.now)
    completed_at = models.DateTimeField("تاريخ الإنجاز", null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_tasks")
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tasks"
        ordering = ["due_date", "-id"]
        indexes = [
            models.Index(fields=["status", "due_date"]),
            models.Index(fields=["unit", "status"]),
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["priority", "status"]),
            models.Index(fields=["source"]),
            models.Index(fields=["last_activity_at"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(check=Q(progress__gte=0) & Q(progress__lte=100), name="task_progress_range"),
            models.CheckConstraint(check=Q(due_date__gte=models.F("start_date")), name="task_due_after_start"),
        ]

    def __str__(self):
        return f"{self.number or '—'} {self.title}"

    def get_absolute_url(self):
        return reverse("tasks:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"T-{self.created_at:%Y}-{self.pk:04d}"
            Task.objects.filter(pk=self.pk).update(number=self.number)

    # ===== خصائص محسوبة =====
    @property
    def is_open(self):
        return self.status not in TERMINAL_STATUSES

    @property
    def is_done(self):
        return self.status in DONE_STATUSES

    @property
    def is_late(self):
        return self.status in ACTIVE_STATUSES and self.due_date < timezone.localdate()

    @property
    def days_remaining(self):
        return (self.due_date - timezone.localdate()).days

    @property
    def days_overdue(self):
        return max(0, -self.days_remaining)

    @property
    def completed_on_time(self):
        return bool(self.completed_at and timezone.localtime(self.completed_at).date() <= self.due_date)

    @property
    def status_color(self):
        return STATUS_STYLE.get(self.status, ("#6c757d", ""))[0]

    @property
    def priority_color(self):
        return PRIORITY_STYLE.get(self.priority, "#6c757d")

    @property
    def participants(self):
        return [a.employee for a in self.assignees.all() if a.role == AssigneeRole.PARTICIPANT]

    @property
    def participant_units(self):
        return [u.unit for u in self.task_units.all() if u.role == UnitRole.PARTICIPANT]

    @property
    def decision(self):
        return self.decisions.select_related("meeting").first()

    @property
    def open_obstacle(self):
        return self.obstacles.filter(status__in=[ObstacleStatus.OPEN, ObstacleStatus.RESPONDED]).order_by("-created_at").first()


class TaskAssignee(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignees")
    employee = models.ForeignKey("organization.Employee", on_delete=models.PROTECT, related_name="task_assignments")
    role = models.CharField(max_length=20, choices=AssigneeRole.choices, default=AssigneeRole.PARTICIPANT)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_assignees"
        constraints = [
            models.UniqueConstraint(fields=["task", "employee"], name="uniq_task_employee"),
            models.UniqueConstraint(fields=["task"], condition=Q(role="primary"), name="one_primary_owner_per_task"),
        ]
        indexes = [models.Index(fields=["employee", "role"])]


class TaskUnit(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="task_units")
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="task_links")
    role = models.CharField(max_length=20, choices=UnitRole.choices, default=UnitRole.PARTICIPANT)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_units"
        constraints = [
            models.UniqueConstraint(fields=["task", "unit"], name="uniq_task_unit"),
            models.UniqueConstraint(fields=["task"], condition=Q(role="lead"), name="one_lead_unit_per_task"),
        ]


class TaskSubtask(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="subtasks")
    title = models.CharField("العنوان", max_length=250)
    assignee = models.ForeignKey("organization.Employee", verbose_name="المسؤول", null=True, blank=True, on_delete=models.SET_NULL, related_name="subtasks")
    due_date = models.DateField("الموعد النهائي", null=True, blank=True)
    status = models.CharField("الحالة", max_length=20, choices=SubtaskStatus.choices, default=SubtaskStatus.NEW)
    progress = models.PositiveSmallIntegerField("نسبة الإنجاز", default=0)
    comment = models.TextField("تعليق", blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "task_subtasks"
        ordering = ["sort_order", "id"]


class TaskStatusHistory(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, choices=Status.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=Status.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_status_history"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["task", "created_at"])]


class TaskUpdate(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="updates")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="task_updates")
    progress_before = models.PositiveSmallIntegerField()
    progress_after = models.PositiveSmallIntegerField()
    comment = models.TextField("تعليق التحديث")
    done_work = models.TextField("الأعمال المنجزة")
    remaining_work = models.TextField("الأعمال المتبقية", blank=True)
    update_date = models.DateField("تاريخ التحديث", default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_updates"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["task", "created_at"])]


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="task_comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField("نص التعليق")
    mentioned_employees = models.ManyToManyField("organization.Employee", blank=True, related_name="mentions", db_table="task_comment_mentions")
    mentioned_units = models.ManyToManyField("organization.Unit", blank=True, related_name="mentions", db_table="task_comment_unit_mentions")
    obstacle = models.ForeignKey("TaskObstacle", null=True, blank=True, on_delete=models.SET_NULL, related_name="comments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_comments"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["task", "created_at"])]


class TaskAttachment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    subtask = models.ForeignKey(TaskSubtask, null=True, blank=True, on_delete=models.SET_NULL, related_name="attachments")
    comment = models.ForeignKey(TaskComment, null=True, blank=True, on_delete=models.SET_NULL, related_name="attachments")
    update = models.ForeignKey(TaskUpdate, null=True, blank=True, on_delete=models.SET_NULL, related_name="attachments")
    obstacle = models.ForeignKey("TaskObstacle", null=True, blank=True, on_delete=models.SET_NULL, related_name="attachments")
    file = models.FileField(upload_to=secure_upload_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=20, default="other")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_attachments"
        ordering = ["-created_at"]

    @property
    def icon(self):
        return {"image": "bi-file-earmark-image", "pdf": "bi-file-earmark-pdf", "word": "bi-file-earmark-word",
                "excel": "bi-file-earmark-excel"}.get(self.kind, "bi-file-earmark")


class TaskObstacle(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="obstacles")
    obstacle_type = models.CharField("نوع العائق", max_length=30, choices=ObstacleType.choices)
    description = models.TextField("وصف المشكلة")
    cause_party = models.CharField("الجهة المسببة", max_length=150, blank=True)
    needs_admin_decision = models.BooleanField("يحتاج قرارًا إداريًا", default=False)
    required_action = models.TextField("الإجراء المطلوب", blank=True)
    intervener = models.ForeignKey("organization.Employee", verbose_name="المطلوب منه التدخل", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="obstacles_to_handle")
    expected_resolution_date = models.DateField("تاريخ متوقع للحل", null=True, blank=True)
    impact = models.CharField("درجة التأثير", max_length=20, choices=Impact.choices, default=Impact.MEDIUM)
    status = models.CharField(max_length=20, choices=ObstacleStatus.choices, default=ObstacleStatus.OPEN)
    previous_task_status = models.CharField(max_length=20, blank=True)
    response = models.TextField("الرد", blank=True)
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_obstacles"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["task", "status"]), models.Index(fields=["status", "needs_admin_decision"])]

    @property
    def is_open(self):
        return self.status != ObstacleStatus.RESOLVED

    @property
    def duration_days(self):
        end = self.resolved_at or timezone.now()
        return (end - self.created_at).days


class EscalationRule(models.Model):
    class Trigger(models.TextChoices):
        BEFORE_DUE = "before_due", "قبل الاستحقاق"
        ON_DUE = "on_due", "في يوم الاستحقاق"
        AFTER_DUE = "after_due", "بعد الاستحقاق (تأخير)"

    class Action(models.TextChoices):
        NOTIFY = "notify", "تنبيه"
        ESCALATE = "escalate", "تصعيد"

    name = models.CharField("اسم القاعدة", max_length=150)
    trigger = models.CharField("المشغّل", max_length=20, choices=Trigger.choices)
    days = models.PositiveSmallIntegerField("عدد الأيام", default=0)
    action = models.CharField("الإجراء", max_length=20, choices=Action.choices, default=Action.NOTIFY)
    targets = models.JSONField("المستهدفون", default=list)
    level = models.PositiveSmallIntegerField("مستوى التصعيد", default=0, help_text="0 تنبيه فقط، 1 رئيس الوحدة، 2 مساعد المدير التنفيذي، 3 المدير التنفيذي")
    priorities = models.JSONField("الأولويات المشمولة", default=list, blank=True, help_text="فارغ = جميع الأولويات")
    is_active = models.BooleanField("مفعلة", default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "escalation_rules"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.name

    @property
    def targets_display(self):
        labels = dict(EscalationTarget.choices)
        return "، ".join(labels.get(t, t) for t in self.targets)

    @property
    def priorities_display(self):
        if not self.priorities:
            return "جميع الأولويات"
        labels = dict(Priority.choices)
        return "، ".join(labels.get(p, p) for p in self.priorities)


class TaskEscalation(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="escalations")
    rule = models.ForeignKey(EscalationRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="escalations")
    kind = models.CharField(max_length=20, choices=EscalationRule.Action.choices, default=EscalationRule.Action.ESCALATE)
    level = models.PositiveSmallIntegerField(default=1)
    escalated_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="received_escalations")
    reason = models.TextField(blank=True)
    is_manual = models.BooleanField(default=False)
    due_date_snapshot = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_escalations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task", "rule", "due_date_snapshot"]),
            models.Index(fields=["escalated_to", "resolved"]),
        ]
