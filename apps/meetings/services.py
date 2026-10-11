from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.core.files import validate_upload
from apps.core.permissions import has_perm
from apps.notifications.services import notify

from .models import DecisionAttachment, MeetingDecision

DONE = {"completed", "closed"}


def recalc_decision(decision):
    """نسبة تنفيذ القرار = متوسط إنجاز المهام المرتبطة (المهمة تحتسب 100% فقط بعد اعتمادها/اكتمالها)."""
    from apps.tasks.constants import ACTIVE_STATUSES, Status

    tasks = list(decision.tasks.exclude(status=Status.CANCELLED).only("status", "progress", "due_date"))
    if decision.status == MeetingDecision.Status.CANCELLED:
        return decision
    today = timezone.localdate()
    if not tasks:
        pct, status = 0, MeetingDecision.Status.NEW
    else:
        pct = round(sum(100 if t.status in DONE else min(t.progress, 90) for t in tasks) / len(tasks))
        done = sum(1 for t in tasks if t.status in DONE)
        late = any(t.status in ACTIVE_STATUSES and t.due_date < today for t in tasks)
        if done == len(tasks):
            status = MeetingDecision.Status.IMPLEMENTED
        elif late:
            status = MeetingDecision.Status.DELAYED
        elif done:
            status = MeetingDecision.Status.PARTIAL
        else:
            status = MeetingDecision.Status.IN_PROGRESS
    if (pct, status) != (decision.implementation_pct, decision.status):
        MeetingDecision.objects.filter(pk=decision.pk).update(implementation_pct=pct, status=status)
        decision.implementation_pct, decision.status = pct, status
    return decision


def sync_task_decisions(task):
    for d in task.decisions.all():
        recalc_decision(d)


def add_decision_attachment(decision, user, f):
    kind = validate_upload(f)
    return DecisionAttachment.objects.create(decision=decision, file=f, original_name=f.name[:255], size=f.size,
                                             kind=kind, uploaded_by=user)


@transaction.atomic
def create_decision(*, user, data, files=()):
    if not has_perm(user, "decisions.manage"):
        raise PermissionDenied("ليس لديك صلاحية إدارة القرارات")
    decision = MeetingDecision.objects.create(created_by=user, **data)
    for f in files:
        add_decision_attachment(decision, user, f)
    audit.log("decision.created", user=user, obj=decision, description=f"قرار {decision.number}: {decision.text[:200]}")
    if decision.followup_owner and decision.followup_owner.user_id:
        notify([decision.followup_owner.user], "decision_assigned", f"أُسندت إليك متابعة القرار {decision.number}",
               decision.text[:200], actor=user, url=decision.get_absolute_url())
    return decision


@transaction.atomic
def convert_to_tasks(decision, *, user, items):
    """
    تحويل قرار إلى مهمة أو عدة مهام. تُنقل بيانات القرار تلقائيًا (رقمه، الاجتماع، النص، التاريخ،
    اللجنة، المرفقات) ويحدد المستخدم فقط: الوحدة، المسؤول، المشاركين، الاستحقاق، الأولوية.
    items: [{title, unit, owner, participants, due_date, priority}]
    """
    from apps.tasks.constants import Source
    from apps.tasks.models import TaskAttachment
    from apps.tasks.services import create_task

    if not has_perm(user, "decisions.manage"):
        raise PermissionDenied("ليس لديك صلاحية تحويل القرارات إلى مهام")
    if decision.status == MeetingDecision.Status.CANCELLED:
        raise ValidationError("لا يمكن تحويل قرار ملغى")
    if not items:
        raise ValidationError("أضف مهمة واحدة على الأقل")
    meeting = decision.meeting
    created = []
    for i, item in enumerate(items, 1):
        title = (item.get("title") or "").strip() or f"تنفيذ القرار {decision.number}"
        description = (
            f"{decision.text}\n\n— مصدر المهمة: القرار رقم {decision.number} بتاريخ {decision.decision_date:%Y-%m-%d}"
            f"\n— الاجتماع: {meeting.number} – {meeting.title}\n— اللجنة: {meeting.committee}"
        )
        task = create_task(
            user=user,
            data={
                "title": title,
                "description": description,
                "source": Source.MEETING_DECISION,
                "source_reference": f"قرار {decision.number} / اجتماع {meeting.number}",
                "unit": item["unit"],
                "owner": item.get("owner"),
                "start_date": timezone.localdate(),
                "due_date": item["due_date"],
                "priority": item.get("priority") or "normal",
                "expected_result": f"تنفيذ القرار رقم {decision.number}",
            },
            participants=item.get("participants") or [],
            participant_units=item.get("participant_units") or [],
            decision=decision,
        )
        for att in decision.attachments.all():
            TaskAttachment.objects.create(task=task, file=att.file.name, original_name=att.original_name,
                                          size=att.size, kind=att.kind, uploaded_by=user)
        created.append(task)
    recalc_decision(decision)
    return created
