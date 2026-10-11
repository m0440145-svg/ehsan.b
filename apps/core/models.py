from django.conf import settings
from django.db import models


class SystemSetting(models.Model):
    """إعدادات قابلة للتعديل من لوحة الإعدادات (قواعد المتابعة، التنبيهات، حالة المحرك)."""

    key = models.CharField("المفتاح", max_length=100, unique=True)
    value = models.JSONField("القيمة", default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "system_settings"
        verbose_name = "إعداد نظام"

    def __str__(self):
        return self.key
