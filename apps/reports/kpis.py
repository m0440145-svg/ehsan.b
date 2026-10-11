"""
حساب مؤشرات الأداء (KPIs):
- نسبة الإنجاز = المكتملة ÷ الإجمالي × 100
- الالتزام بالمواعيد = المكتملة في موعدها ÷ إجمالي المكتملة × 100
- نسبة التأخير = المتأخرة ÷ المفتوحة × 100
- نسبة التعثر = المتعثرة ÷ المفتوحة × 100
- متوسط زمن الإنجاز، متوسط أيام التأخير، متوسط مدة التعثر
"""
from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from apps.tasks.constants import ACTIVE_STATUSES, DONE_STATUSES, OPEN_OBSTACLE_STATUSES, OPEN_STATUSES, Priority, Status
from apps.tasks.models import TaskObstacle
from apps.tasks.selectors import followup_filter

DONE = list(DONE_STATUSES)


def pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0


def _avg(values):
    values = list(values)
    return round(sum(values) / len(values), 1) if values else 0


def compute_kpis(qs, today=None):
    today = today or timezone.localdate()
    qs = qs.order_by()
    agg = qs.aggregate(
        total=Count("id"),
        open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
        done=Count("id", filter=Q(status__in=DONE)),
        in_progress=Count("id", filter=Q(status=Status.IN_PROGRESS)),
        overdue=Count("id", filter=Q(status__in=ACTIVE_STATUSES, due_date__lt=today)),
        critical=Count("id", filter=Q(status__in=OPEN_STATUSES, priority=Priority.CRITICAL)),
        pending=Count("id", filter=Q(status=Status.PENDING_APPROVAL)),
        on_time=Count("id", filter=Q(status__in=DONE, completed_at__date__lte=F("due_date"))),
        avg_progress=Avg("progress", filter=Q(status__in=OPEN_STATUSES)),
    )
    agg["stalled"] = followup_filter(qs, "stalled").count()
    agg["completed_month"] = qs.filter(status__in=DONE, completed_at__year=today.year, completed_at__month=today.month).count()
    done_rows = qs.filter(status__in=DONE, completed_at__isnull=False).values_list("start_date", "completed_at")
    agg["avg_completion_days"] = _avg(max((timezone.localtime(c).date() - s).days, 0) for s, c in done_rows)
    late_rows = qs.filter(status__in=ACTIVE_STATUSES, due_date__lt=today).values_list("due_date", flat=True)
    agg["avg_delay_days"] = _avg((today - d).days for d in late_rows)
    obstacles = TaskObstacle.objects.filter(task__in=qs.values("pk"))
    agg["avg_stall_days"] = _avg(o.duration_days for o in obstacles)
    agg["open_obstacles"] = obstacles.filter(status__in=OPEN_OBSTACLE_STATUSES).count()
    agg["completion_rate"] = pct(agg["done"], agg["total"])
    agg["on_time_rate"] = pct(agg["on_time"], agg["done"])
    agg["delay_rate"] = pct(agg["overdue"], agg["open"])
    agg["stall_rate"] = pct(agg["stalled"], agg["open"])
    agg["avg_progress"] = round(agg["avg_progress"] or 0)
    return agg


def group_stats(qs, by="unit", today=None):
    """إحصاءات مجمعة حسب الوحدة أو المسؤول الرئيسي."""
    today = today or timezone.localdate()
    if by == "unit":
        keys = ("unit_id", "unit__name")
    else:
        keys = ("owner_id", "owner__full_name")
    rows = (
        qs.order_by().values(*keys).annotate(
            total=Count("id"),
            open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
            done=Count("id", filter=Q(status__in=DONE)),
            in_progress=Count("id", filter=Q(status__in=[Status.IN_PROGRESS, Status.ASSIGNED, Status.RETURNED, Status.WAITING_REPLY, Status.WAITING_EXTERNAL])),
            overdue=Count("id", filter=Q(status__in=ACTIVE_STATUSES, due_date__lt=today)),
            stalled=Count("id", filter=Q(status=Status.STALLED)),
            critical=Count("id", filter=Q(status__in=OPEN_STATUSES, priority=Priority.CRITICAL)),
            pending=Count("id", filter=Q(status=Status.PENDING_APPROVAL)),
            on_time=Count("id", filter=Q(status__in=DONE, completed_at__date__lte=F("due_date"))),
            avg_progress=Avg("progress"),
        )
    )
    result = []
    for r in rows:
        r["id"] = r[keys[0]]
        r["name"] = r[keys[1]]
        r["completion_rate"] = pct(r["done"], r["total"])
        r["on_time_rate"] = pct(r["on_time"], r["done"])
        r["delay_rate"] = pct(r["overdue"], r["open"])
        r["avg_progress"] = round(r["avg_progress"] or 0)
        result.append(r)
    return sorted(result, key=lambda x: (-x["total"], x["name"] or ""))
