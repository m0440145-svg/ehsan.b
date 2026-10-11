"""سجل التقارير الاثني عشر. كل تقرير يعيد أعمدة وصفوفًا ورسمًا بيانيًا اختياريًا وملخصًا."""
from collections import defaultdict
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from apps.meetings.models import MeetingDecision
from apps.tasks.constants import (
    ACTIVE_STATUSES,
    DONE_STATUSES,
    OPEN_OBSTACLE_STATUSES,
    OPEN_STATUSES,
    PRIORITY_WEIGHT,
    Priority,
)
from apps.tasks.models import TaskEscalation
from apps.tasks.selectors import followup_filter

from .kpis import compute_kpis, group_stats, pct


def _d(value):
    if not value:
        return "—"
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def apply_filters(qs, f):
    if f.get("date_from"):
        qs = qs.filter(created_at__date__gte=f["date_from"])
    if f.get("date_to"):
        qs = qs.filter(created_at__date__lte=f["date_to"])
    from apps.tasks.models import Task

    if f.get("unit"):
        qs = qs.filter(pk__in=Task.objects.filter(Q(unit_id=f["unit"]) | Q(task_units__unit_id=f["unit"])).values("pk"))
    if f.get("employee"):
        qs = qs.filter(pk__in=Task.objects.filter(assignees__employee_id=f["employee"]).values("pk"))
    if f.get("status"):
        qs = qs.filter(status=f["status"])
    if f.get("priority"):
        qs = qs.filter(priority=f["priority"])
    if f.get("source"):
        qs = qs.filter(source=f["source"])
    if f.get("project"):
        qs = qs.filter(project=f["project"])
    if f.get("meeting"):
        qs = qs.filter(pk__in=Task.objects.filter(decisions__meeting_id=f["meeting"]).values("pk"))
    return qs


def _task_rows(qs, extra=None):
    rows = []
    for t in qs.select_related("unit", "owner"):
        row = [t.number, t.title, t.unit.name, t.owner.full_name, t.get_priority_display(), _d(t.due_date),
               t.get_status_display(), f"{t.progress}%"]
        if extra:
            row += extra(t)
        rows.append(row)
    return rows


TASK_COLS = ["رقم المهمة", "العنوان", "الوحدة", "المسؤول", "الأولوية", "الاستحقاق", "الحالة", "الإنجاز"]


def r_units(qs, f):
    stats = group_stats(qs, "unit")
    rows = [[s["name"], s["total"], s["open"], s["done"], s["overdue"], s["stalled"], s["critical"], s["pending"],
             f"{s['completion_rate']}%", f"{s['on_time_rate']}%"] for s in stats]
    return {
        "columns": ["الوحدة", "الإجمالي", "المفتوحة", "المكتملة", "المتأخرة", "المتعثرة", "الحرجة", "بانتظار اعتماد", "نسبة الإنجاز", "الالتزام بالمواعيد"],
        "rows": rows,
        "chart": {"type": "bar", "labels": [s["name"] for s in stats], "datasets": [
            {"label": "مكتملة", "data": [s["done"] for s in stats], "color": "#198754"},
            {"label": "مفتوحة", "data": [s["open"] - s["overdue"] for s in stats], "color": "#1c6dd0"},
            {"label": "متأخرة", "data": [s["overdue"] for s in stats], "color": "#dc3545"},
        ], "stacked": True},
    }


def r_employees(qs, f):
    stats = group_stats(qs, "owner")
    rows = [[s["name"], s["total"], s["done"], s["in_progress"], s["overdue"], s["stalled"], f"{s['avg_progress']}%",
             f"{s['completion_rate']}%", f"{s['on_time_rate']}%"] for s in stats]
    return {
        "columns": ["الموظف", "إجمالي المهام", "المكتمل", "الجاري", "المتأخر", "المتعثر", "متوسط الإنجاز", "نسبة الإنجاز", "الالتزام"],
        "rows": rows,
        "chart": {"type": "bar", "labels": [s["name"] for s in stats], "datasets": [
            {"label": "مكتمل", "data": [s["done"] for s in stats], "color": "#198754"},
            {"label": "جارٍ", "data": [s["in_progress"] for s in stats], "color": "#1c6dd0"},
            {"label": "متأخر", "data": [s["overdue"] for s in stats], "color": "#dc3545"},
            {"label": "متعثر", "data": [s["stalled"] for s in stats], "color": "#8b1a1a"},
        ], "stacked": True, "horizontal": True},
    }


def r_overdue(qs, f):
    items = followup_filter(qs, "overdue").order_by("due_date")
    return {"columns": TASK_COLS + ["أيام التأخير", "مستوى التصعيد"],
            "rows": _task_rows(items, lambda t: [t.days_overdue, t.escalation_level])}


def r_stalled(qs, f):
    items = followup_filter(qs, "stalled")

    def extra(t):
        ob = t.open_obstacle
        return [ob.get_obstacle_type_display() if ob else "—", ob.description[:80] if ob else "—",
                ob.duration_days if ob else "—", "نعم" if ob and ob.needs_admin_decision else "لا"]

    return {"columns": TASK_COLS + ["نوع العائق", "السبب", "مدة التعثر (يوم)", "يحتاج قرارًا"], "rows": _task_rows(items, extra)}


def r_commitment(qs, f):
    stats = group_stats(qs, "unit")
    rows = [[s["name"], s["done"], s["on_time"], s["done"] - s["on_time"], f"{s['on_time_rate']}%"] for s in stats if s["done"]]
    return {
        "columns": ["الوحدة", "المكتملة", "في موعدها", "بعد موعدها", "نسبة الالتزام"],
        "rows": rows,
        "chart": {"type": "bar", "labels": [r[0] for r in rows], "datasets": [
            {"label": "نسبة الالتزام %", "data": [s["on_time_rate"] for s in stats if s["done"]], "color": "#cf6028"}]},
    }


def r_completed(qs, f):
    items = qs.filter(status__in=DONE_STATUSES).order_by("-completed_at")
    return {"columns": TASK_COLS + ["تاريخ الإنجاز", "في الموعد", "مدة الإنجاز (يوم)"],
            "rows": _task_rows(items, lambda t: [_d(t.completed_at), "نعم" if t.completed_on_time else "لا",
                                                 (timezone.localtime(t.completed_at).date() - t.start_date).days if t.completed_at else "—"])}


def r_stale(qs, f):
    items = followup_filter(qs, "stale").order_by("last_activity_at")
    now = timezone.now()
    return {"columns": TASK_COLS + ["آخر تحديث", "أيام بدون تحديث"],
            "rows": _task_rows(items, lambda t: [_d(t.last_activity_at), (now - t.last_activity_at).days])}


def _decisions(f):
    ds = MeetingDecision.objects.select_related("meeting", "followup_owner")
    if f.get("meeting"):
        ds = ds.filter(meeting_id=f["meeting"])
    if f.get("date_from"):
        ds = ds.filter(decision_date__gte=f["date_from"])
    if f.get("date_to"):
        ds = ds.filter(decision_date__lte=f["date_to"])
    return ds


def r_decisions(qs, f):
    rows = [[d.number, d.meeting.number, d.meeting.title, d.meeting.committee, d.text[:120], _d(d.decision_date),
             d.get_status_display()] for d in _decisions(f)]
    return {"columns": ["رقم القرار", "رقم الاجتماع", "الاجتماع", "اللجنة", "نص القرار", "التاريخ", "الحالة"], "rows": rows}


def r_decision_impl(qs, f):
    today = timezone.localdate()
    rows, labels, data = [], [], []
    for d in _decisions(f).prefetch_related("tasks"):
        tasks = [t for t in d.tasks.all() if t.status != "cancelled"]
        done = sum(1 for t in tasks if t.status in DONE_STATUSES)
        late = sum(1 for t in tasks if t.status in ACTIVE_STATUSES and t.due_date < today)
        stalled = sum(1 for t in tasks if t.status == "stalled")
        rows.append([d.number, d.meeting.title, d.text[:100], len(tasks), done, late, stalled, f"{d.implementation_pct}%",
                     d.followup_owner.full_name if d.followup_owner else "—"])
        labels.append(d.number)
        data.append(d.implementation_pct)
    return {"columns": ["رقم القرار", "الاجتماع", "نص القرار", "المهام الناتجة", "المكتملة", "المتأخرة", "المتعثرة", "نسبة التنفيذ", "مسؤول المتابعة"],
            "rows": rows,
            "chart": {"type": "bar", "labels": labels, "datasets": [{"label": "نسبة التنفيذ %", "data": data, "color": "#cf6028"}]}}


def r_workload(qs, f):
    today = timezone.localdate()
    load = defaultdict(lambda: {"open": 0, "critical": 0, "overdue": 0, "weight": 0, "unit": ""})
    for t in qs.filter(status__in=OPEN_STATUSES).select_related("owner", "unit"):
        e = load[t.owner.full_name]
        e["unit"] = t.unit.name
        e["open"] += 1
        e["weight"] += PRIORITY_WEIGHT.get(t.priority, 2)
        e["critical"] += t.priority == Priority.CRITICAL
        e["overdue"] += t.status in ACTIVE_STATUSES and t.due_date < today
    items = sorted(load.items(), key=lambda kv: -kv[1]["weight"])
    rows = [[name, v["unit"], v["open"], v["critical"], v["overdue"], v["weight"],
             "مرتفع" if v["weight"] >= 15 else ("متوسط" if v["weight"] >= 8 else "منخفض")] for name, v in items]
    return {"columns": ["الموظف", "الوحدة", "المهام المفتوحة", "الحرجة", "المتأخرة", "الوزن الموزون بالأولوية", "مستوى الضغط"],
            "rows": rows,
            "chart": {"type": "bar", "labels": [r[0] for r in rows], "horizontal": True,
                      "datasets": [{"label": "ضغط العمل الموزون", "data": [r[5] for r in rows], "color": "#f18927"}]}}


def r_avg_time(qs, f):
    groups = defaultdict(list)
    by_priority = defaultdict(list)
    for t in qs.filter(status__in=DONE_STATUSES, completed_at__isnull=False).select_related("unit"):
        days = max((timezone.localtime(t.completed_at).date() - t.start_date).days, 0)
        groups[t.unit.name].append(days)
        by_priority[t.get_priority_display()].append(days)
    rows = [[k, len(v), round(sum(v) / len(v), 1), min(v), max(v)] for k, v in sorted(groups.items())]
    rows += [["— حسب الأولوية: " + k, len(v), round(sum(v) / len(v), 1), min(v), max(v)] for k, v in by_priority.items()]
    unit_rows = [r for r in rows if not str(r[0]).startswith("—")]
    return {"columns": ["البند", "عدد المكتملة", "متوسط زمن الإنجاز (يوم)", "الأقل", "الأعلى"], "rows": rows,
            "chart": {"type": "bar", "labels": [r[0] for r in unit_rows],
                      "datasets": [{"label": "متوسط الأيام", "data": [r[2] for r in unit_rows], "color": "#1c6dd0"}]}}


def r_escalations(qs, f):
    items = TaskEscalation.objects.filter(task__in=qs.values("pk")).select_related("task", "task__unit", "escalated_to", "rule", "created_by")
    rows = [[e.task.number, e.task.title, e.task.unit.name, e.get_kind_display(), e.level,
             e.escalated_to.full_name if e.escalated_to else "—", "يدوي" if e.is_manual else "آلي",
             e.reason[:80], _d(e.created_at), "نعم" if e.resolved else "لا"] for e in items[:1000]]
    return {"columns": ["رقم المهمة", "المهمة", "الوحدة", "النوع", "المستوى", "إلى", "الطريقة", "السبب", "التاريخ", "تمت المعالجة"], "rows": rows}


REPORTS = {
    "units": ("تقرير أداء الوحدات", "bi-diagram-3", r_units),
    "employees": ("تقرير أداء الموظفين", "bi-people", r_employees),
    "overdue": ("تقرير المهام المتأخرة", "bi-alarm", r_overdue),
    "stalled": ("تقرير المهام المتعثرة", "bi-exclamation-octagon", r_stalled),
    "commitment": ("تقرير الالتزام بالمواعيد", "bi-calendar-check", r_commitment),
    "completed": ("تقرير المهام المكتملة", "bi-check2-circle", r_completed),
    "stale": ("تقرير المهام بدون تحديث", "bi-clock-history", r_stale),
    "decisions": ("تقرير قرارات الاجتماعات", "bi-journal-text", r_decisions),
    "decision_impl": ("تقرير تنفيذ القرارات", "bi-journal-check", r_decision_impl),
    "workload": ("تقرير ضغط العمل", "bi-speedometer2", r_workload),
    "avg_time": ("تقرير متوسط زمن الإنجاز", "bi-stopwatch", r_avg_time),
    "escalations": ("تقرير التصعيدات", "bi-graph-up-arrow", r_escalations),
}


def build_report(key, qs, filters):
    title, icon, fn = REPORTS[key]
    qs = apply_filters(qs, filters)
    result = fn(qs, filters)
    result.update({"key": key, "title": title, "icon": icon, "kpis": compute_kpis(qs)})
    return result
