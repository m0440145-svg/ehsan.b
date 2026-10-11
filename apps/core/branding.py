"""بيانات الجهة وشعارها: تُحفظ في الإعدادات، والشعار ملف صورة يُخدم عبر رابط عام (يظهر في صفحة الدخول)."""
import mimetypes
import uuid

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404

from apps.audit import services as audit

from .files import validate_upload
from .settings_service import get_setting, set_setting


def get_org():
    return get_setting("organization")


def save_org(data, user=None, logo=None, remove_logo=False):
    org = get_org()
    old = dict(org)
    for key in ("name", "short_name", "platform_name", "city", "license_no", "phone", "email", "website", "address"):
        if key in data:
            org[key] = (data.get(key) or "").strip()
    if not org["name"]:
        raise ValidationError({"name": "اسم الجهة مطلوب"})
    org["short_name"] = org["short_name"] or org["name"]
    if remove_logo and org.get("logo"):
        default_storage.delete(org["logo"])
        org["logo"] = ""
    if logo:
        if validate_upload(logo) != "image":
            raise ValidationError({"logo": "الشعار يجب أن يكون صورة PNG أو JPG أو WEBP"})
        ext = (logo.name.rsplit(".", 1)[-1] or "png").lower()
        path = default_storage.save(f"branding/logo_{uuid.uuid4().hex[:10]}.{ext}", logo)
        if org.get("logo"):
            default_storage.delete(org["logo"])
        org["logo"] = path
    if "setup_completed" in data:
        org["setup_completed"] = bool(data["setup_completed"])
    set_setting("organization", org, user)
    audit.log("settings.updated", user=user, description="تحديث بيانات الجهة",
              old={k: old.get(k) for k in ("name", "short_name", "phone", "email")},
              new={k: org.get(k) for k in ("name", "short_name", "phone", "email")})
    return org


def logo_view(request):
    path = get_org().get("logo")
    if not path or not default_storage.exists(path):
        raise Http404
    resp = FileResponse(default_storage.open(path, "rb"), content_type=mimetypes.guess_type(path)[0] or "image/png")
    resp["Cache-Control"] = "public, max-age=3600"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
