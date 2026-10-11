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


DEFAULT_UNITS = [
    ("BOARD", "مجلس الإدارة", "الجهة العليا المسؤولة عن رسم السياسات واعتماد الخطط الاستراتيجية."),
    ("ED", "المدير التنفيذي", "قيادة العمل التنفيذي ومتابعة تحقيق أهداف الجمعية."),
    ("SEC", "السكرتارية", "إدارة المراسلات والاجتماعات وتنظيم أعمال الإدارة التنفيذية."),
    ("EDA", "مساعد المدير التنفيذي", "دعم المدير التنفيذي في المتابعة والتنسيق بين الوحدات."),
    ("COMM", "وحدة الاتصال المؤسسي", "الإعلام والتسويق وإدارة الهوية والعلاقات العامة."),
    ("TECH", "وحدة التقنية والتحول الرقمي", "الأنظمة والبنية التقنية والتحول الرقمي."),
    ("CARE", "وحدة الخدمات الرعوية", "دراسة الحالات وصرف المساعدات ورعاية الأسر المستفيدة."),
    ("COMTY", "وحدة خدمة المجتمع", "المبادرات المجتمعية والشراكات المحلية."),
    ("DEV", "وحدة الخدمات التنموية", "برامج التمكين والتدريب والأسر المنتجة."),
    ("VOL", "وحدة التطوع", "استقطاب المتطوعين وإدارة الفرص التطوعية."),
    ("HR", "وحدة الموارد البشرية", "التوظيف وتقييم الأداء وشؤون الموظفين."),
    ("FIN", "وحدة الشؤون المالية والإدارية", "المحاسبة والميزانيات والمشتريات."),
    ("AUDIT", "وحدة المراجعة الداخلية", "مراجعة الإجراءات والامتثال والرقابة الداخلية."),
    ("INV", "وحدة الاستثمار", "تنمية الموارد والأوقاف والاستثمارات."),
    ("EXC", "وحدة التميز المؤسسي", "الجودة والتميز المؤسسي وقياس الأداء."),
    ("SUP", "وحدة الخدمات المساندة", "الصيانة والمستودعات والخدمات العامة."),
]


def create_default_units():
    from apps.organization.models import Unit

    created = 0
    for i, (code, name, desc) in enumerate(DEFAULT_UNITS):
        _, was_created = Unit.objects.get_or_create(name=name, defaults={"code": code, "description": desc, "sort_order": i})
        created += was_created
    return created


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
