from django import template
from django.utils import timezone
from django.utils.html import format_html

from apps.core.permissions import has_perm
from apps.tasks.constants import PRIORITY_STYLE, STATUS_STYLE, Priority, Status

register = template.Library()

STATUS_LABELS = dict(Status.choices)
PRIORITY_LABELS = dict(Priority.choices)


@register.filter
def can(user, code):
    return has_perm(user, code)


@register.simple_tag
def status_badge(status, label=None):
    color, icon = STATUS_STYLE.get(status, ("#6c757d", "bi-circle"))
    return format_html(
        '<span class="badge status-badge" style="--c:{}"><i class="bi {}"></i> {}</span>',
        color, icon, label or STATUS_LABELS.get(status, status),
    )


@register.simple_tag
def priority_badge(priority):
    color = PRIORITY_STYLE.get(priority, "#6c757d")
    icon = "bi-lightning-charge-fill" if priority == "critical" else "bi-flag-fill"
    return format_html('<span class="badge priority-badge" style="--c:{}"><i class="bi {}"></i> {}</span>',
                       color, icon, PRIORITY_LABELS.get(priority, priority))


@register.simple_tag
def progress_bar(value, task=None, size="sm"):
    value = int(value or 0)
    if value >= 100:
        tone = "success"
    elif task is not None and task.is_late:
        tone = "danger"
    elif value >= 50:
        tone = "primary"
    else:
        tone = "brand"
    return format_html(
        '<div class="progress-wrap progress-{}" title="نسبة الإنجاز {}%" data-bs-toggle="tooltip">'
        '<div class="progress"><div class="progress-bar bg-{}" style="width:{}%"></div></div>'
        '<span class="progress-num">{}%</span></div>',
        size, value, tone, value, value,
    )


@register.simple_tag
def days_badge(task):
    if not task.is_open or task.status == Status.PENDING_APPROVAL:
        if task.is_done:
            return format_html('<span class="days-chip done"><i class="bi bi-check2"></i> منجزة</span>')
        return format_html('<span class="days-chip muted">—</span>')
    d = task.days_remaining
    if d < 0:
        return format_html('<span class="days-chip late"><i class="bi bi-alarm"></i> متأخرة {} يوم</span>', -d)
    if d == 0:
        return format_html('<span class="days-chip soon"><i class="bi bi-hourglass-bottom"></i> تستحق اليوم</span>')
    if d <= 3:
        return format_html('<span class="days-chip soon"><i class="bi bi-hourglass-split"></i> متبقي {} يوم</span>', d)
    return format_html('<span class="days-chip ok">متبقي {} يوم</span>', d)


@register.filter
def initials(name):
    parts = (name or "").split()
    if not parts:
        return "؟"
    return parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")


@register.filter
def filesize(num):
    num = int(num or 0)
    for unit in ("بايت", "ك.ب", "م.ب"):
        if num < 1024:
            return f"{num:.0f} {unit}"
        num /= 1024
    return f"{num:.1f} ج.ب"


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def since(dt):
    if not dt:
        return "—"
    delta = timezone.now() - dt
    if delta.days >= 1:
        return f"منذ {delta.days} يوم"
    hours = delta.seconds // 3600
    if hours:
        return f"منذ {hours} ساعة"
    minutes = delta.seconds // 60
    return f"منذ {minutes} دقيقة" if minutes else "الآن"


@register.simple_tag(takes_context=True)
def qs_replace(context, **kwargs):
    query = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v is None or v == "":
            query.pop(k, None)
        else:
            query[k] = v
    return query.urlencode()
