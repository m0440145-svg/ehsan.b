"""القائمة الجانبية: كل عنصر يظهر فقط لمن يملك الصلاحية المطلوبة."""
from django.urls import reverse

from .permissions import has_perm

MENU = [
    {"label": "لوحة التحكم", "icon": "bi-grid-1x2", "url": "dashboard:home"},
    {"label": "المهام", "icon": "bi-list-check", "key": "tasks", "children": [
        {"label": "إضافة مهمة", "url": "tasks:create", "perm": "tasks.create"},
        {"label": "مهامي", "url": "tasks:my", "needs_employee": True},
        {"label": "مهام وحدتي", "url": "tasks:unit", "perm": "tasks.view_unit"},
        {"label": "جميع المهام", "url": "tasks:all", "perm": "tasks.view_all"},
    ]},
    {"label": "مركز المتابعة", "icon": "bi-binoculars", "key": "followup", "children": [
        {"label": "المتأخرة", "url": "followup:center", "query": "tab=overdue"},
        {"label": "المتعثرة", "url": "followup:center", "query": "tab=stalled"},
        {"label": "تستحق قريبًا", "url": "followup:center", "query": "tab=due_soon"},
        {"label": "بدون تحديث", "url": "followup:center", "query": "tab=stale"},
        {"label": "بانتظار رد", "url": "followup:center", "query": "tab=waiting_reply"},
        {"label": "بانتظار اعتماد", "url": "followup:center", "query": "tab=pending_approval"},
        {"label": "التصعيدات", "url": "followup:center", "query": "tab=escalated"},
    ]},
    {"label": "القرارات", "icon": "bi-journal-text", "key": "decisions", "perm": "decisions.view", "children": [
        {"label": "قرارات الاجتماعات", "url": "meetings:decisions"},
        {"label": "متابعة تنفيذ القرارات", "url": "meetings:tracking"},
        {"label": "الاجتماعات", "url": "meetings:meetings"},
    ]},
    {"label": "التقارير", "icon": "bi-bar-chart-line", "key": "reports", "perm": "reports.view", "children": [
        {"label": "جميع التقارير", "url": "reports:index"},
        {"label": "أداء الوحدات", "url": "reports:report", "args": ["units"]},
        {"label": "أداء الموظفين", "url": "reports:report", "args": ["employees"]},
        {"label": "الالتزام بالمواعيد", "url": "reports:report", "args": ["commitment"]},
        {"label": "التعثر والتأخير", "url": "reports:report", "args": ["stalled"]},
    ]},
    {"label": "الإدارة", "icon": "bi-buildings", "key": "admin", "children": [
        {"label": "الوحدات", "url": "organization:units", "perm": "admin.units"},
        {"label": "الموظفون", "url": "organization:employees", "perm": "admin.employees"},
        {"label": "المستخدمون", "url": "accounts:users", "perm": "admin.users"},
        {"label": "الصلاحيات", "url": "accounts:roles", "perm": "admin.roles"},
        {"label": "سجل التدقيق", "url": "core:audit", "perm": "admin.audit"},
    ]},
    {"label": "الإعدادات", "icon": "bi-gear", "key": "settings", "perm": "settings.manage", "children": [
        {"label": "حالات المهام", "url": "core:statuses"},
        {"label": "الأولويات", "url": "core:priorities"},
        {"label": "أنواع المهام", "url": "core:task_types"},
        {"label": "قواعد المتابعة", "url": "core:rules"},
        {"label": "قواعد التصعيد", "url": "core:escalation_rules"},
        {"label": "التنبيهات", "url": "core:notification_settings"},
    ]},
]


def _visible(item, user):
    if item.get("perm") and not has_perm(user, item["perm"]):
        return False
    if item.get("needs_employee") and not getattr(user, "employee", None):
        return False
    return True


def build_menu(request):
    user = request.user
    path = request.path
    full = request.get_full_path()
    items = []
    for item in MENU:
        if not _visible(item, user):
            continue
        node = {"label": item["label"], "icon": item["icon"], "key": item.get("key", item["label"])}
        if "children" in item:
            children = []
            for c in item["children"]:
                if not _visible(c, user):
                    continue
                url = reverse(c["url"], args=c.get("args", []))
                if c.get("query"):
                    url += "?" + c["query"]
                active = full == url if c.get("query") else path == url
                children.append({"label": c["label"], "url": url, "active": active})
            if not children:
                continue
            node["children"] = children
            node["active"] = any(c["active"] for c in children)
        else:
            node["url"] = reverse(item["url"])
            node["active"] = path == node["url"]
        items.append(node)
    return items
