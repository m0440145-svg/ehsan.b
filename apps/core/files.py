"""حماية رفع الملفات: قائمة بيضاء للامتدادات، حد للحجم، فحص التوقيع (magic bytes)، أسماء عشوائية."""
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

ALLOWED = {
    # الامتداد: (النوع، التوقيعات المقبولة)
    ".pdf": ("pdf", [b"%PDF"]),
    ".png": ("image", [b"\x89PNG"]),
    ".jpg": ("image", [b"\xff\xd8\xff"]),
    ".jpeg": ("image", [b"\xff\xd8\xff"]),
    ".gif": ("image", [b"GIF8"]),
    ".webp": ("image", [b"RIFF"]),
    ".docx": ("word", [b"PK\x03\x04"]),
    ".doc": ("word", [b"\xd0\xcf\x11\xe0"]),
    ".xlsx": ("excel", [b"PK\x03\x04"]),
    ".xls": ("excel", [b"\xd0\xcf\x11\xe0"]),
    ".pptx": ("other", [b"PK\x03\x04"]),
    ".csv": ("excel", None),
    ".txt": ("other", None),
}

KIND_LABELS = {"image": "صورة", "pdf": "PDF", "word": "Word", "excel": "Excel", "other": "ملف"}


def validate_upload(f):
    """يتحقق من الملف ويعيد نوعه. يرفع ValidationError عند الرفض."""
    name = os.path.basename(f.name or "")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise ValidationError(f"نوع الملف «{ext or 'بدون امتداد'}» غير مسموح. المسموح: {', '.join(sorted(ALLOWED))}")
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if f.size > max_bytes:
        raise ValidationError(f"حجم الملف يتجاوز الحد المسموح ({settings.MAX_UPLOAD_SIZE_MB} ميجابايت)")
    kind, signatures = ALLOWED[ext]
    head = f.read(8)
    f.seek(0)
    if signatures and not any(head.startswith(sig) for sig in signatures):
        raise ValidationError("محتوى الملف لا يطابق امتداده")
    if signatures is None and b"\x00" in head:
        raise ValidationError("الملف النصي يحتوي على بيانات ثنائية غير صالحة")
    return kind


def secure_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"uploads/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"
