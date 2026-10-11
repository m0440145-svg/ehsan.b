from django.conf import settings
from django.db import models

from .events import EVENTS


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    event = models.CharField(max_length=40, choices=[(k, v[0]) for k, v in EVENTS.items()])
    title = models.CharField(max_length=250)
    body = models.TextField(blank=True)
    task = models.ForeignKey("tasks.Task", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    channels = models.JSONField(default=list, blank=True)  # القنوات التي أُرسل عبرها
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "created_at"])]

    @property
    def icon(self):
        return EVENTS.get(self.event, ("", "bi-bell", "secondary"))[1]

    @property
    def tone(self):
        return EVENTS.get(self.event, ("", "bi-bell", "secondary"))[2]

    @property
    def event_label(self):
        return EVENTS.get(self.event, (self.event,))[0]
