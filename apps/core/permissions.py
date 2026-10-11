"""
التحكم في الوصول القائم على الأدوار (RBAC).
- الصلاحيات تُعرّف هنا كرموز (codes) وتُخزن في جدول permissions.
- كل دور مرتبط بمجموعة صلاحيات قابلة للتعديل من شاشة الصلاحيات.
- نطاق البيانات (أي المهام يراها المستخدم) يُطبق في apps.tasks.selectors.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

PERMISSIONS = [
    ("dashboard.executive", "لوحة الإدارة التنفيذية", "لوحات التحكم"),
    ("dashboard.unit", "لوحة الوحدة", "لوحات التحكم"),
    ("tasks.create", "إنشاء مهمة", "المهام"),
    ("tasks.edit", "تعديل المهام وإدارة الإسناد", "المهام"),
    ("tasks.view_all", "عرض جميع المهام", "المهام"),
    ("tasks.view_unit", "عرض مهام الوحدة", "المهام"),
    ("tasks.view_confidential", "عرض المهام السرية", "المهام"),
    ("tasks.approve", "اعتماد / رفض / إعادة المهام", "المهام"),
    ("tasks.escalate", "تصعيد المهام", "المهام"),
    ("tasks.cancel", "إيقاف وإلغاء المهام", "المهام"),
    ("followup.view", "مركز المتابعة", "المتابعة"),
    ("decisions.view", "عرض قرارات الاجتماعات", "القرارات"),
    ("decisions.manage", "إدارة القرارات وتحويلها إلى مهام", "القرارات"),
    ("reports.view", "عرض التقارير", "التقارير"),
    ("reports.export", "تصدير التقارير", "التقارير"),
    ("admin.units", "إدارة الوحدات التنظيمية", "الإدارة"),
    ("admin.employees", "إدارة الموظفين", "الإدارة"),
    ("admin.users", "إدارة المستخدمين", "الإدارة"),
    ("admin.roles", "إدارة الأدوار والصلاحيات", "الإدارة"),
    ("admin.audit", "عرض سجل التدقيق", "الإدارة"),
    ("settings.manage", "إدارة إعدادات النظام", "الإعدادات"),
]

ALL_CODES = [p[0] for p in PERMISSIONS]


class RoleCode:
    ADMIN = "admin"
    EXECUTIVE_DIRECTOR = "executive_director"
    ED_ASSISTANT = "ed_assistant"
    UNIT_HEAD = "unit_head"
    EMPLOYEE = "employee"
    VIEWER = "viewer"


ROLES = [
    (RoleCode.ADMIN, "مسؤول النظام"),
    (RoleCode.EXECUTIVE_DIRECTOR, "المدير التنفيذي"),
    (RoleCode.ED_ASSISTANT, "مساعد المدير التنفيذي"),
    (RoleCode.UNIT_HEAD, "رئيس الوحدة"),
    (RoleCode.EMPLOYEE, "موظف"),
    (RoleCode.VIEWER, "مستخدم للعرض فقط"),
]

_MANAGEMENT = [
    "dashboard.executive", "dashboard.unit", "tasks.create", "tasks.edit", "tasks.view_all",
    "tasks.view_unit", "tasks.view_confidential", "tasks.approve", "tasks.escalate", "tasks.cancel",
    "followup.view", "decisions.view", "decisions.manage", "reports.view", "reports.export",
]

ROLE_DEFAULT_PERMISSIONS = {
    RoleCode.ADMIN: ALL_CODES,
    RoleCode.EXECUTIVE_DIRECTOR: _MANAGEMENT + ["admin.audit"],
    RoleCode.ED_ASSISTANT: _MANAGEMENT,
    RoleCode.UNIT_HEAD: [
        "dashboard.unit", "tasks.create", "tasks.edit", "tasks.view_unit", "tasks.approve",
        "tasks.escalate", "tasks.cancel", "followup.view", "decisions.view", "reports.view", "reports.export",
    ],
    RoleCode.EMPLOYEE: [],
    RoleCode.VIEWER: ["dashboard.executive", "tasks.view_all", "followup.view", "decisions.view", "reports.view"],
}


def has_perm(user, code):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return code in user.permission_codes


def perm_required(*codes, any_of=False):
    """مزخرف للعروض: يشترط امتلاك الصلاحيات (أو إحداها عند any_of)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            checks = [has_perm(request.user, c) for c in codes]
            if (any_of and not any(checks)) or (not any_of and not all(checks)):
                raise PermissionDenied("ليس لديك صلاحية للوصول إلى هذه الصفحة")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class HasPermCode(BasePermission):
    """صلاحية DRF: تعرّف العروض required_perms = {"GET": "...", "POST": "..."} أو required_perm."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        perms = getattr(view, "required_perms", None)
        code = None
        if isinstance(perms, dict):
            code = perms.get(request.method) or perms.get("*")
        else:
            code = getattr(view, "required_perm", None)
        return True if not code else has_perm(request.user, code)
