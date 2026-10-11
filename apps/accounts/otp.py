"""
طبقة التحقق الثنائي (OTP) قابلة للتوسعة.
لتفعيلها: OTP_ENABLED=True وتفعيل otp_enabled للمستخدم، ثم استبدال المزوّد
بمزوّد رسائل SMS/WhatsApp فعلي عبر OTP_PROVIDER.
"""
import hashlib
import logging
import secrets

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

logger = logging.getLogger("security")

SESSION_KEY = "otp_pending"
TTL_SECONDS = 300


class BaseOTPProvider:
    def send(self, user, code):  # pragma: no cover - واجهة
        raise NotImplementedError


class LogOTPProvider(BaseOTPProvider):
    """مزوّد تطويري: يكتب الرمز في سجل الأمان فقط."""

    def send(self, user, code):
        logger.info("OTP للمستخدم %s: %s", user.email, code)


def _hash(code):
    return hashlib.sha256(code.encode()).hexdigest()


def is_required(user):
    return settings.OTP_ENABLED and user.otp_enabled


def start(request, user):
    code = f"{secrets.randbelow(10**6):06d}"
    request.session[SESSION_KEY] = {
        "user_id": user.pk,
        "hash": _hash(code),
        "expires": timezone.now().timestamp() + TTL_SECONDS,
        "tries": 0,
    }
    import_string(settings.OTP_PROVIDER)().send(user, code)


def verify(request, code):
    data = request.session.get(SESSION_KEY)
    if not data or timezone.now().timestamp() > data["expires"]:
        return None
    data["tries"] += 1
    request.session[SESSION_KEY] = data
    if data["tries"] > 5:
        request.session.pop(SESSION_KEY, None)
        return None
    if secrets.compare_digest(_hash(code.strip()), data["hash"]):
        request.session.pop(SESSION_KEY, None)
        return data["user_id"]
    return None
