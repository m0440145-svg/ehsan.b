"""
محددات الوصول والاستعلامات: كل الشاشات وواجهات API تمر من هنا لضمان أن المستخدم
لا يرى إلا البيانات المصرح بها.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.permissions import RoleCode, has_perm
from apps.core.settings_service import get_rules

from .constants import ACTIVE_STATUSES, OPEN_OBSTACLE_STATUSES, OPEN_STATUSES, Confidentiality, Priority, Status
from .models import Task


def employee_of(user):
    return getattr(user, "employee", None) if user and user.is_authenticated else None


def headed_unit_ids(user):
    emp = employee_of(user)
    if not emp:
        return []
    return list(emp.headed_units.values_list("id", flat=True))


def base_queryset():
    return Task.objects.select_related("unit", "owner", "owner__user", "task_type", "created_by")


def visible_tasks(user):
    """المهام التي يحق للمستخدم رؤيتها حسب الدور ومستوى السرية."""
    if not user or not user.is_authenticated:
        return Task.objects.none()
    emp = employee_of(user)
    qs = base_queryset()
    if has_perm(user, "tasks.view_all"):
        scope = Q()
    else:
        scope = Q(created_by=user)
        if emp:
            scope |= Q(assignees__employee=emp) | Q(subtasks__assignee=emp)
            if has_perm(user, "tasks.view_unit"):
                units = headed_unit_ids(user)
                scope |= Q(unit_id__in=units) | Q(task_units__unit_id__in=units)
    if not has_perm(user, "tasks.view_confidential"):
        involved = Q(created_by=user)
        if emp:
            involved |= Q(assignees__employee=emp)
            units = headed_unit_ids(user)
            involved |= Q(confidentiality=Confidentiality.CONFIDENTIAL, unit_id__in=units)
        scope &= Q(confidentiality=Confidentiality.NORMAL) | involved
    ids = Task.objects.filter(scope).values("pk")
    return qs.filter(pk__in=ids)


def my_tasks(user):
    emp = employee_of(user)
    if not emp:
        return Task.objects.none()
    ids = Task.objects.filter(Q(assignees__employee=emp) | Q(subtasks__assignee=emp)).values("pk")
    return base_queryset().filter(pk__in=ids)


def unit_tasks(user):
    units = headed_unit_ids(user)
    emp = employee_of(user)
    if not units and emp:
        units = list(emp.units.values_list("id", flat=True))
    ids = Task.objects.filter(Q(unit_id__in=units) | Q(task_units__unit_id__in=units)).values("pk")
    return visible_tasks(user).filter(pk__in=ids)


# ===== صلاحيات على مستوى المهمة =====

def is_involved(user, task):
    emp = employee_of(user)
    return bool(emp and task.assignees.filter(employee=emp).exists())


def is_task_manager(user, task):
    """رئيس وحدة المهمة أو المدير المباشر للمسؤول أو الإدارة العليا."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.role_code in (RoleCode.ADMIN, RoleCode.EXECUTIVE_DIRECTOR, RoleCode.ED_ASSISTANT):
        return True
    emp = employee_of(user)
    if not emp:
        return False
    if task.unit.head_id == emp.pk:
        return True
    if task.owner.manager_id == emp.pk:
        return True
    return task.created_by_id == user.pk and has_perm(user, "tasks.edit")


def can_view(user, task):
    return visible_tasks(user).filter(pk=task.pk).exists()


def can_edit(user, task):
    return task.is_open and has_perm(user, "tasks.edit") and is_task_manager(user, task)


def can_update_progress(user, task):
    if not task.is_open or task.status in (Status.PENDING_APPROVAL, Status.ON_HOLD):
        return False
    return is_involved(user, task) or (has_perm(user, "tasks.edit") and is_task_manager(user, task))


def can_comment(user, task):
    return can_view(user, task) and user.role_code != RoleCode.VIEWER


def can_register_obstacle(user, task):
    return task.is_open and task.status != Status.PENDING_APPROVAL and (is_involved(user, task) or is_task_manager(user, task))


def can_respond_obstacle(user, obstacle):
    emp = employee_of(user)
    if emp and obstacle.intervener_id == emp.pk:
        return True
    return is_task_manager(user, obstacle.task) and user.role_code != RoleCode.VIEWER


def can_approve(user, task):
    if not has_perm(user, "tasks.approve") or not is_task_manager(user, task):
        return False
    emp = employee_of(user)
    # لا يعتمد المسؤول الرئيسي إنجاز نفسه إلا المدير التنفيذي
    if emp and task.owner_id == emp.pk and user.role_code != RoleCode.EXECUTIVE_DIRECTOR:
        return False
    return True


def can_escalate(user, task):
    return task.is_open and (has_perm(user, "tasks.escalate") or is_involved(user, task)) and user.role_code != RoleCode.VIEWER


def can_change_status(user, task):
    return task.is_open and (is_involved(user, task) or can_edit(user, task))


# ===== استعلامات مركز المتابعة =====

FOLLOWUP_TABS = [
    ("overdue", "المتأخرة", "bi-alarm", "danger"),
    ("stalled", "المتعثرة", "bi-exclamation-octagon", "stalled"),
    ("due_today", "تستحق اليوم", "bi-calendar-event", "warning"),
    ("due_soon", "تستحق خلال 3 أيام", "bi-hourglass-split", "warning"),
    ("stale", "بدون تحديث", "bi-clock-history", "secondary"),
    ("waiting_reply", "بانتظار رد", "bi-chat-left-dots", "yellow"),
    ("pending_approval", "بانتظار اعتماد", "bi-patch-question", "purple"),
    ("critical", "الحرجة", "bi-lightning-charge", "danger"),
    ("escalated", "المصعدة للإدارة", "bi-graph-up-arrow", "danger"),
    ("returned", "المهام المعادة", "bi-arrow-counterclockwise", "brand"),
]


def followup_filter(qs, tab, rules=None):
    rules = rules or get_rules()
    today = timezone.localdate()
    if tab == "overdue":
        return qs.filter(status__in=ACTIVE_STATUSES, due_date__lt=today)
    if tab == "overdue_long":
        return qs.filter(status__in=ACTIVE_STATUSES, due_date__lt=today - timedelta(days=int(rules["overdue_long_days"])))
    if tab == "stalled":
        ids = Task.objects.filter(Q(status=Status.STALLED) | Q(obstacles__status__in=OPEN_OBSTACLE_STATUSES)).values("pk")
        return qs.filter(pk__in=ids, status__in=OPEN_STATUSES)
    if tab == "due_today":
        return qs.filter(status__in=ACTIVE_STATUSES, due_date=today)
    if tab == "due_soon":
        return qs.filter(status__in=ACTIVE_STATUSES, due_date__gt=today, due_date__lte=today + timedelta(days=int(rules["due_soon_days"])))
    if tab == "stale":
        threshold = timezone.now() - timedelta(days=int(rules["stale_days"]))
        return qs.filter(status__in=ACTIVE_STATUSES, last_activity_at__lt=threshold)
    if tab == "waiting_reply":
        return qs.filter(status__in=[Status.WAITING_REPLY, Status.WAITING_EXTERNAL])
    if tab == "pending_approval":
        return qs.filter(status=Status.PENDING_APPROVAL)
    if tab == "critical":
        return qs.filter(status__in=OPEN_STATUSES, priority=Priority.CRITICAL)
    if tab == "escalated":
        return qs.filter(status__in=OPEN_STATUSES, escalation_level__gte=1)
    if tab == "returned":
        return qs.filter(status=Status.RETURNED)
    if tab == "needs_ed_decision":
        ids = Task.objects.filter(obstacles__status__in=OPEN_OBSTACLE_STATUSES, obstacles__needs_admin_decision=True).values("pk")
        return qs.filter(status__in=OPEN_STATUSES).filter(Q(pk__in=ids) | Q(needs_ed_decision=True) | Q(escalation_level__gte=3))
    return qs
