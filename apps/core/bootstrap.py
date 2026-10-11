"""تهيئة البيانات المرجعية: الصلاحيات، الأدوار، قواعد التصعيد الافتراضية، أنواع المهام."""
from apps.accounts.models import Permission, Role
from apps.tasks.engine import ensure_default_rules
from apps.tasks.models import TaskType

from .permissions import PERMISSIONS, ROLE_DEFAULT_PERMISSIONS, ROLES

TASK_TYPES = [
    ("تشغيلية", "أعمال تشغيلية متكررة"), ("مشروع", "مهمة ضمن مشروع"), ("إدارية", "إجراء إداري"),
    ("مالية", "مهمة مالية"), ("تقنية", "تطوير أو دعم تقني"), ("إعلامية", "محتوى واتصال مؤسسي"),
    ("ميدانية", "زيارة أو خدمة ميدانية"), ("تقرير", "إعداد تقرير"),
]


def ensure_reference_data(reset_role_permissions=False):
    perms = {}
    for code, name, group in PERMISSIONS:
        p, _ = Permission.objects.update_or_create(code=code, defaults={"name": name, "group": group})
        perms[code] = p
    for code, name in ROLES:
        role, created = Role.objects.get_or_create(code=code, defaults={"name": name})
        if created or reset_role_permissions or code == "admin":
            role.permissions.set([perms[c] for c in ROLE_DEFAULT_PERMISSIONS[code]])
    ensure_default_rules()
    for name, desc in TASK_TYPES:
        TaskType.objects.get_or_create(name=name, defaults={"description": desc})
