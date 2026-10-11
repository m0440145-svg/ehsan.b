import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import LoginAttempt, User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.permissions import RoleCode, has_perm, perm_required
from apps.core.settings_service import get_rules, get_setting
from apps.meetings.models import MeetingDecision
from apps.notifications.models import Notification
from apps.organization.models import Employee, Unit
from apps.reports.kpis import compute_kpis, group_stats
from apps.tasks import selectors
from apps.tasks.constants import ACTIVE_STATUSES, OPEN_STATUSES, STATUS_STYLE, Priority, Status
from apps.tasks.models import Task, TaskComment
from apps.tasks.views import with_people


@login_required
def home(request):
    role = request.user.role_code
    if request.user.is_superuser or role == RoleCode.ADMIN:
        return redirect("dashboard:admin")
    if role in (RoleCode.EXECUTIVE_DIRECTOR, RoleCode.ED_ASSISTANT, RoleCode.VIEWER):
        return redirect("dashboard:executive")
    if role == RoleCode.UNIT_HEAD:
        return redirect("dashboard:unit")
    return redirect("dashboard:employee")


def _status_chart(qs):
    labels = dict(Status.choices)
    rows = {}
    for s in qs.order_by().values_list("status", flat=True):
        rows[s] = rows.get(s, 0) + 1
    keys = [s for s in Status.values if s in rows]
    return {"type": "doughnut", "labels": [labels[k] for k in keys],
            "datasets": [{"label": "المهام", "data": [rows[k] for k in keys], "colors": [STATUS_STYLE[k][0] for k in keys]}]}


@login_required
def employee_dashboard(request):
    emp = selectors.employee_of(request.user)
    if not emp:
        messages.info(request, "حسابك غير مرتبط بملف موظف؛ تم توجيهك إلى اللوحة المناسبة")
        return redirect("dashboard:executive" if has_perm(request.user, "dashboard.executive") else "tasks:search")
    rules = get_rules()
    today = timezone.localdate()
    mine = selectors.my_tasks(request.user)
    kpis = compute_kpis(mine)
    kpis["due_soon"] = selectors.followup_filter(mine, "due_soon", rules).count() + selectors.followup_filter(mine, "due_today", rules).count()
    week = today + timedelta(days=7)
    comments = (TaskComment.objects.filter(task__in=mine.values("pk")).exclude(author=request.user)
                .select_related("author", "task").order_by("-created_at")[:6])
    ctx = {
        "kpis": kpis, "rules": rules, "emp": emp,
        "today_tasks": with_people(selectors.followup_filter(mine, "due_today", rules)),
        "upcoming": with_people(mine.filter(status__in=ACTIVE_STATUSES, due_date__gt=today, due_date__lte=week).order_by("due_date")[:8]),
        "critical": with_people(mine.filter(status__in=OPEN_STATUSES, priority__in=[Priority.CRITICAL, Priority.URGENT]).order_by("due_date")[:8]),
        "stale": with_people(selectors.followup_filter(mine, "stale", rules).order_by("last_activity_at")[:8]),
        "overdue": with_people(selectors.followup_filter(mine, "overdue", rules).order_by("due_date")[:8]),
        "comments": comments,
        "notifications": Notification.objects.filter(recipient=request.user).select_related("task")[:8],
        "status_chart": json.dumps(_status_chart(mine), ensure_ascii=False),
    }
    return render(request, "dashboard/employee.html", ctx)


@login_required
def unit_dashboard(request):
    user = request.user
    if not (has_perm(user, "dashboard.unit") or has_perm(user, "dashboard.executive")):
        raise PermissionDenied("لوحة الوحدة متاحة لرؤساء الوحدات والإدارة")
    if has_perm(user, "tasks.view_all"):
        units = Unit.objects.filter(is_active=True)
    else:
        units = Unit.objects.filter(pk__in=selectors.headed_unit_ids(user))
    if not units.exists():
        messages.info(request, "لم يتم تعيينك رئيسًا لأي وحدة")
        return redirect("dashboard:employee")
    unit = units.filter(pk=request.GET.get("unit")).first() if request.GET.get("unit") else None
    unit = unit or units.first()
    rules = get_rules()
    qs = selectors.visible_tasks(user).filter(pk__in=Task.objects.filter(unit=unit).values("pk")) \
        if not has_perm(user, "tasks.view_all") else Task.objects.filter(unit=unit)
    qs = qs.select_related("unit", "owner")
    kpis = compute_kpis(qs)
    by_emp = group_stats(qs, "owner")
    members = Employee.objects.filter(units=unit).order_by("full_name")
    emp_chart = {"type": "bar", "stacked": True, "labels": [e["name"] for e in by_emp], "datasets": [
        {"label": "مكتمل", "data": [e["done"] for e in by_emp], "color": "#198754"},
        {"label": "جارٍ", "data": [e["in_progress"] - 0 for e in by_emp], "color": "#1c6dd0"},
        {"label": "متأخر", "data": [e["overdue"] for e in by_emp], "color": "#dc3545"},
        {"label": "متعثر", "data": [e["stalled"] for e in by_emp], "color": "#8b1a1a"},
    ]}
    load_chart = {"type": "bar", "horizontal": True, "labels": [e["name"] for e in by_emp],
                  "datasets": [{"label": "المهام المفتوحة", "data": [e["open"] for e in by_emp], "color": "#f18927"}]}
    committed = sorted([e for e in by_emp if e["done"]], key=lambda e: (-e["on_time_rate"], -e["done"]))[:5]
    with_overdue = [e for e in by_emp if e["overdue"]]
    ctx = {
        "unit": unit, "units": units, "kpis": kpis, "by_emp": by_emp, "members": members, "rules": rules,
        "emp_chart": json.dumps(emp_chart, ensure_ascii=False), "load_chart": json.dumps(load_chart, ensure_ascii=False),
        "status_chart": json.dumps(_status_chart(qs), ensure_ascii=False),
        "committed": committed, "with_overdue": with_overdue,
        "critical": with_people(qs.filter(status__in=OPEN_STATUSES, priority=Priority.CRITICAL).order_by("due_date")[:8]),
        "pending": with_people(qs.filter(status=Status.PENDING_APPROVAL).order_by("completed_at")[:8]),
        "stalled": with_people(selectors.followup_filter(qs, "stalled", rules)[:8]),
    }
    return render(request, "dashboard/unit.html", ctx)


@perm_required("dashboard.executive")
def executive_dashboard(request):
    rules = get_rules()
    qs = selectors.visible_tasks(request.user)
    kpis = compute_kpis(qs)
    units = group_stats(qs, "unit")
    top_units = sorted([u for u in units if u["total"]], key=lambda u: (-u["completion_rate"], -u["done"]))[:5]
    late_units = sorted([u for u in units if u["overdue"]], key=lambda u: (-u["overdue"], -u["delay_rate"]))[:5]
    perf_chart = {"type": "bar", "stacked": True, "labels": [u["name"] for u in units], "datasets": [
        {"label": "مكتملة", "data": [u["done"] for u in units], "color": "#198754"},
        {"label": "قيد التنفيذ", "data": [max(u["open"] - u["overdue"] - u["stalled"], 0) for u in units], "color": "#1c6dd0"},
        {"label": "متأخرة", "data": [u["overdue"] for u in units], "color": "#dc3545"},
        {"label": "متعثرة", "data": [u["stalled"] for u in units], "color": "#8b1a1a"},
    ]}
    load_chart = {"type": "bar", "horizontal": True, "labels": [u["name"] for u in units],
                  "datasets": [{"label": "المهام المفتوحة", "data": [u["open"] for u in units], "color": "#f18927"}]}
    decisions = MeetingDecision.objects.exclude(status__in=["implemented", "cancelled"]).select_related("meeting", "followup_owner").order_by("decision_date")[:8]
    ctx = {
        "kpis": kpis, "units": units, "top_units": top_units, "late_units": late_units, "rules": rules,
        "perf_chart": json.dumps(perf_chart, ensure_ascii=False), "load_chart": json.dumps(load_chart, ensure_ascii=False),
        "status_chart": json.dumps(_status_chart(qs), ensure_ascii=False),
        "critical": with_people(qs.filter(status__in=OPEN_STATUSES, priority=Priority.CRITICAL).order_by("due_date")[:8]),
        "stalled": with_people(selectors.followup_filter(qs, "stalled", rules)[:8]),
        "needs_ed": with_people(selectors.followup_filter(qs, "needs_ed_decision", rules)[:8]),
        "stale": with_people(selectors.followup_filter(qs, "stale", rules).order_by("last_activity_at")[:8]),
        "overdue_long": with_people(selectors.followup_filter(qs, "overdue_long", rules).order_by("due_date")[:8]),
        "decisions": decisions,
    }
    return render(request, "dashboard/executive.html", ctx)


@login_required
def admin_dashboard(request):
    if not (request.user.is_superuser or request.user.role_code == RoleCode.ADMIN):
        raise PermissionDenied
    now = timezone.now()
    ctx = {
        "stats": {
            "users": User.objects.count(), "active_users": User.objects.filter(is_active=True).count(),
            "locked": User.objects.filter(locked_until__gt=now).count(), "units": Unit.objects.filter(is_active=True).count(),
            "employees": Employee.objects.count(), "tasks": Task.objects.count(),
            "open_tasks": Task.objects.filter(status__in=OPEN_STATUSES).count(),
            "failed_24h": LoginAttempt.objects.filter(success=False, created_at__gte=now - timedelta(days=1)).count(),
        },
        "kpis": compute_kpis(Task.objects.all()),
        "attempts": LoginAttempt.objects.select_related("user")[:10],
        "audit": AuditLog.objects.select_related("user", "task")[:12],
        "engine": get_setting("engine_state"),
        "roles": User.objects.values("role__name").order_by("role__name").annotate(n=Count("id")),
    }
    return render(request, "dashboard/admin.html", ctx)


@perm_required("settings.manage")
@require_POST
def run_engine_now(request):
    from apps.tasks.engine import run_engine

    stats = run_engine()
    audit.log("system.engine_run", description=str(stats))
    messages.success(request, f"تم تشغيل محرك القواعد: تقييم {stats['evaluated']} مهمة، {stats['marked_overdue']} متأخرة جديدة، {stats['escalations']} تصعيد")
    return redirect(request.POST.get("next") or "dashboard:admin")
