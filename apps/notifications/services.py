"""
مركز التنبيهات: notify() نقطة دخول واحدة، وكل قناة (داخل النظام / بريد / WhatsApp)
منفصلة لتسهيل الربط مستقبلًا دون تعديل منطق المهام.
"""
import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Notification

logger = logging.getLogger("apps.notifications")


class InAppChannel:
    code = "in_app"

    def send(self, notification):
        return True  # السجل نفسه هو التنبيه داخل النظام


class EmailChannel:
    code = "email"

    def enabled(self):
        return settings.EMAIL_NOTIFICATIONS_ENABLED

    def send(self, notification):
        if not notification.recipient.email:
            return False
        link = settings.SITE_BASE_URL.rstrip("/") + notification.url if notification.url else ""
        send_mail(
            subject=f"[منصة المهام] {notification.title}",
            message=f"{notification.body}\n\n{link}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient.email],
            fail_silently=True,
        )
        return True


class WhatsAppChannel:
    code = "whatsapp"

    def enabled(self):
        return settings.WHATSAPP_ENABLED and settings.WHATSAPP_API_URL

    def send(self, notification):
        phone = notification.recipient.phone
        if not phone:
            return False
        payload = json.dumps({"to": "966" + phone.lstrip("0"), "text": f"{notification.title}\n{notification.body}"}).encode()
        req = urllib.request.Request(
            settings.WHATSAPP_API_URL, data=payload, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            logger.warning("فشل إرسال WhatsApp إلى %s", phone)
            return False


EXTERNAL_CHANNELS = [EmailChannel(), WhatsAppChannel()]


def notify(recipients, event, title, body="", *, task=None, actor=None, url=None, include_actor=False):
    """ينشئ تنبيهًا لكل مستلم (مستخدمين)، مع استبعاد منفّذ الإجراء افتراضيًا."""
    from apps.core.settings_service import get_setting

    prefs = get_setting("notifications").get(event, {"in_app": True})
    if url is None and task is not None:
        url = task.get_absolute_url()
    seen = set()
    created = []
    for user in recipients:
        if user is None or not getattr(user, "is_active", False) or user.pk in seen:
            continue
        if actor is not None and user.pk == actor.pk and not include_actor:
            continue
        seen.add(user.pk)
        channels = []
        if prefs.get("in_app", True):
            channels.append("in_app")
        n = Notification.objects.create(
            recipient=user, actor=actor, event=event, title=title[:250], body=body, task=task, url=url or "",
            channels=channels,
        )
        created.append(n)
        external = [ch for ch in EXTERNAL_CHANNELS if prefs.get(ch.code) and ch.enabled()]
        if external:
            transaction.on_commit(lambda n=n, ex=external: _dispatch_external(n, ex))
    return created


def _dispatch_external(notification, channels):
    sent = list(notification.channels)
    for ch in channels:
        try:
            if ch.send(notification):
                sent.append(ch.code)
        except Exception:
            logger.exception("فشل إرسال التنبيه عبر %s", ch.code)
    Notification.objects.filter(pk=notification.pk).update(channels=sent)


def mark_read(user, ids=None):
    qs = Notification.objects.filter(recipient=user, is_read=False)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs.update(is_read=True, read_at=timezone.now())
