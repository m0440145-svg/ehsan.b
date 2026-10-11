from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import User, normalize_phone


def find_user(identifier):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    q = Q(email__iexact=identifier)
    phone = normalize_phone(identifier)
    if phone and phone[0].isdigit():
        q |= Q(phone=phone)
    return User.objects.filter(q).select_related("role").first()


class EmailOrPhoneBackend(ModelBackend):
    """تسجيل الدخول بالبريد الإلكتروني أو رقم الجوال مع كلمة المرور."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get("email") or kwargs.get("phone")
        if not identifier or not password:
            return None
        user = find_user(identifier)
        if user is None:
            User().set_password(password)  # تقليل فروق التوقيت لمنع تعداد الحسابات
            return None
        if user.is_locked:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            user = User.objects.select_related("role").get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
