"""آلة الحالات: لا انتقال بين الحالات إلا وفق جدول TRANSITIONS، وكل انتقال يُسجَّل."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit import services as audit

from .constants import MANUAL_TARGETS, TRANSITIONS, Status
from .models import TaskStatusHistory

LABELS = dict(Status.choices)


def label(status):
    return LABELS.get(status, status)


def allowed_targets(task, manual=True):
    targets = TRANSITIONS.get(task.status, set())
    if manual:
        targets = targets & MANUAL_TARGETS
    return [s for s in Status.values if s in targets]


def change_status(task, to, *, user=None, note="", via="action"):
    """via: manual (اختيار المستخدم) / action (إجراء عمل) / system (محرك القواعد)."""
    frm = task.status
    if frm == to:
        return task
    if to not in TRANSITIONS.get(frm, set()):
        raise ValidationError(f"لا يمكن نقل المهمة من «{label(frm)}» إلى «{label(to)}»")
    if via == "manual" and to not in MANUAL_TARGETS:
        raise ValidationError(f"الحالة «{label(to)}» لا تُختار يدويًا، بل تتم عبر الإجراء المخصص لها")
    now = timezone.now()
    task.status = to
    if to in (Status.COMPLETED, Status.PENDING_APPROVAL):
        task.completed_at = task.completed_at or now
    if to == Status.RETURNED:
        task.completed_at = None
    if to == Status.CLOSED:
        task.closed_at = now
    task.save(update_fields=["status", "completed_at", "closed_at", "updated_at"])
    TaskStatusHistory.objects.create(task=task, from_status=frm, to_status=to, changed_by=user, note=note)
    audit.log(
        "task.status_changed", user=user, task=task, description=note, system=(via == "system"),
        old={"الحالة": label(frm)}, new={"الحالة": label(to)},
    )
    from apps.meetings.services import sync_task_decisions

    sync_task_decisions(task)
    return task
