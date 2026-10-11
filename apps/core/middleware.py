import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("apps.core")

_local = threading.local()


def get_current_request():
    return getattr(_local, "request", None)


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class RequestContextMiddleware:
    """يحفظ الطلب الحالي لسجلات التدقيق (عنوان IP والمتصفح)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None


class ForcePasswordChangeMiddleware:
    """يُلزم المستخدم بتغيير كلمة المرور المؤقتة (حسابات أنشأها المسؤول أو استوردها) قبل استخدام المنصة."""

    ALLOWED_PREFIXES = ("/accounts/profile/", "/accounts/logout/", "/static/", "/branding/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and getattr(user, "must_change_password", False)
                and not request.path.startswith(self.ALLOWED_PREFIXES) and not request.path.startswith("/api/")):
            from django.contrib import messages
            from django.shortcuts import redirect

            messages.warning(request, "يرجى تغيير كلمة المرور المؤقتة قبل متابعة استخدام المنصة")
            return redirect("accounts:profile")
        return self.get_response(request)


class RuleEngineMiddleware:
    """
    تشغيل محرك القواعد والتصعيد تلقائيًا كل N دقيقة (حسب الإعدادات) داخل التطبيق.
    في الإنتاج يُفضل جدولة الأمر: python manage.py run_task_engine
    """

    LOCK_KEY = "task-engine-lock"
    LAST_KEY = "task-engine-last"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.TASK_ENGINE_AUTORUN and getattr(request, "user", None) and request.user.is_authenticated:
            try:
                self._maybe_run()
            except Exception:  # لا نسمح لفشل المحرك بإيقاف الطلب
                logger.exception("فشل تشغيل محرك القواعد التلقائي")
        return response

    def _maybe_run(self):
        from apps.core.settings_service import get_rules

        interval = int(get_rules().get("engine_interval_minutes", 10)) * 60
        last = cache.get(self.LAST_KEY)
        now = timezone.now().timestamp()
        if last and now - last < interval:
            return
        if not cache.add(self.LOCK_KEY, 1, 120):
            return
        try:
            from apps.tasks.engine import run_engine

            run_engine()
            cache.set(self.LAST_KEY, now, None)
        finally:
            cache.delete(self.LOCK_KEY)
