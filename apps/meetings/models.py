from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.files import secure_upload_path

COMMITTEES = [
    "مجلس الإدارة",
    "اللجنة التنفيذية",
    "لجنة المراجعة",
    "لجنة الاستثمار",
    "لجنة الموارد البشرية",
    "اجتماع الإدارة التنفيذية",
    "اجتماع رؤساء الوحدات",
]


class Meeting(models.Model):
    number = models.CharField("رقم الاجتماع", max_length=40, unique=True)
    title = models.CharField("اسم الاجتماع", max_length=250)
    committee = models.CharField("اللجنة", max_length=150)
    date = models.DateField("تاريخ الاجتماع", default=timezone.localdate)
    location = models.CharField("المكان", max_length=150, blank=True)
    notes = models.TextField("ملاحظات", blank=True)
    external_ref = models.CharField("مرجع منصة الاجتماعات", max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "meetings"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["committee", "date"])]

    def __str__(self):
        return f"{self.number} - {self.title}"


class MeetingDecision(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "جديد"
        IN_PROGRESS = "in_progress", "قيد التنفيذ"
        PARTIAL = "partial", "منفذ جزئيًا"
        IMPLEMENTED = "implemented", "منفذ"
        DELAYED = "delayed", "متأخر"
        CANCELLED = "cancelled", "ملغى"

    number = models.CharField("رقم القرار", max_length=40, unique=True)
    meeting = models.ForeignKey(Meeting, verbose_name="الاجتماع", on_delete=models.PROTECT, related_name="decisions")
    text = models.TextField("نص القرار")
    decision_date = models.DateField("تاريخ القرار", default=timezone.localdate)
    due_date = models.DateField("الموعد المستهدف للتنفيذ", null=True, blank=True)
    status = models.CharField("حالة القرار", max_length=20, choices=Status.choices, default=Status.NEW)
    followup_owner = models.ForeignKey(
        "organization.Employee", verbose_name="المسؤول عن المتابعة", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="followed_decisions",
    )
    implementation_pct = models.PositiveSmallIntegerField("نسبة التنفيذ", default=0)
    tasks = models.ManyToManyField("tasks.Task", through="DecisionTask", related_name="decisions", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "meeting_decisions"
        ordering = ["-decision_date", "-id"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["meeting", "decision_date"])]

    def __str__(self):
        return f"قرار {self.number}"

    def get_absolute_url(self):
        return reverse("meetings:decision_detail", args=[self.pk])

    @property
    def committee(self):
        return self.meeting.committee


class DecisionAttachment(models.Model):
    decision = models.ForeignKey(MeetingDecision, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=secure_upload_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=20, default="other")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "decision_attachments"


class DecisionTask(models.Model):
    decision = models.ForeignKey(MeetingDecision, on_delete=models.CASCADE, related_name="task_links")
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="decision_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "decision_tasks"
        constraints = [models.UniqueConstraint(fields=["decision", "task"], name="uniq_decision_task")]
