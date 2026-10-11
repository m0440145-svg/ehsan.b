from django.conf import settings
from django.db import models

ACTIONS = {
    "task.created": "إنشاء المهمة",
    "task.updated": "تعديل المهمة",
    "task.owner_changed": "تغيير المسؤول",
    "task.participant_added": "إضافة مشارك",
    "task.participant_removed": "إزالة مشارك",
    "task.unit_added": "إضافة وحدة مشاركة",
    "task.unit_removed": "إزالة وحدة مشاركة",
    "task.due_changed": "تغيير الموعد",
    "task.status_changed": "تغيير الحالة",
    "task.progress_changed": "تغيير نسبة الإنجاز",
    "task.file_uploaded": "رفع ملف",
    "task.comment_added": "إضافة تعليق",
    "task.obstacle_registered": "تسجيل تعثر",
    "task.obstacle_responded": "الرد على التعثر",
    "task.obstacle_resolved": "معالجة العائق",
    "task.returned": "إعادة المهمة",
    "task.rejected": "رفض الإنجاز",
    "task.approval_requested": "طلب اعتماد",
    "task.approved": "اعتماد المهمة",
    "task.closed": "إغلاق المهمة",
    "task.escalated": "تصعيد المهمة",
    "task.subtask_added": "إضافة مهمة فرعية",
    "task.subtask_updated": "تحديث مهمة فرعية",
    "decision.created": "إنشاء قرار",
    "decision.updated": "تعديل قرار",
    "decision.converted": "تحويل قرار إلى مهمة",
    "meeting.created": "إنشاء اجتماع",
    "auth.login": "تسجيل دخول",
    "auth.logout": "تسجيل خروج",
    "auth.login_failed": "محاولة دخول فاشلة",
    "auth.locked": "قفل الحساب",
    "auth.password_changed": "تغيير كلمة المرور",
    "user.created": "إنشاء مستخدم",
    "user.updated": "تعديل مستخدم",
    "role.updated": "تعديل صلاحيات دور",
    "unit.created": "إنشاء وحدة",
    "unit.updated": "تعديل وحدة",
    "employee.created": "إضافة موظف",
    "employee.updated": "تعديل موظف",
    "settings.updated": "تعديل الإعدادات",
    "system.engine_run": "تشغيل محرك القواعد",
    "system.backup": "نسخ احتياطي",
}


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("سجل التدقيق غير قابل للتعديل")

    def delete(self):
        raise PermissionError("سجل التدقيق غير قابل للحذف")


class AuditLog(models.Model):
    """سجل نشاط غير قابل للتعديل أو الحذف (محمي في النموذج وبمشغّل في PostgreSQL)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=60, blank=True)
    task = models.ForeignKey("tasks.Task", null=True, blank=True, on_delete=models.PROTECT, related_name="activity")
    description = models.TextField(blank=True)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["task", "created_at"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["user", "created_at"]),
        ]

    @property
    def action_label(self):
        return ACTIONS.get(self.action, self.action)

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("سجل التدقيق غير قابل للتعديل")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("سجل التدقيق غير قابل للحذف")
