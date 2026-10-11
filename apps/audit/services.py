import datetime
import decimal
import logging

from apps.core.middleware import client_ip, get_current_request

from .models import AuditLog

logger = logging.getLogger("apps.audit")


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if hasattr(value, "pk"):
        return str(value)
    return value


def log(action, *, user=None, task=None, obj=None, description="", old=None, new=None, system=False):
    """system=True: إجراء آلي (محرك القواعد) لا يُنسب لمستخدم الطلب الحالي."""
    request = None if system else get_current_request()
    if user is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        user = request.user
    entry = AuditLog.objects.create(
        user=user if (user and user.is_authenticated) else None,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else ("Task" if task else ""),
        object_id=str(obj.pk) if obj is not None else (str(task.pk) if task else ""),
        task=task,
        description=description,
        old_values=_json_safe(old) if old else None,
        new_values=_json_safe(new) if new else None,
        ip_address=client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
    )
    logger.debug("audit %s user=%s task=%s %s", action, getattr(user, "pk", None), getattr(task, "pk", None), description)
    return entry
