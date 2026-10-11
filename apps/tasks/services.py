"""
طبقة الخدمات للمهام: كل منطق الأعمال (الإنشاء، الإسناد، التحديث، العوائق، الاعتماد، التصعيد)
يمر من هنا، وتستدعيها واجهات الويب وواجهات REST API على حد سواء.
"""
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.core.files import validate_upload
from apps.core.permissions import RoleCode, has_perm
from apps.core.settings_service import get_rules
from apps.notifications.services import notify
from apps.organization.models import Employee, Unit

from . import selectors
from .constants import (
    ESCALATION_LEVEL_LABELS,
    MANAGER_TARGETS,
    OPEN_OBSTACLE_STATUSES,
    AssigneeRole,
    ObstacleStatus,
    Priority,
    Status,
    SubtaskStatus,
    UnitRole,
)
from .models import (
    Task,
    TaskAssignee,
    TaskAttachment,
    TaskComment,
    TaskEscalation,
    TaskObstacle,
    TaskSubtask,
    TaskUnit,
    TaskUpdate,
)
from .workflow import change_status, label

TASK_EDITABLE_FIELDS = {
    "title": "العنوان", "description": "الوصف", "source": "المصدر", "source_reference": "مرجع المصدر",
    "task_type": "نوع المهمة", "project": "المشروع", "unit": "الوحدة المسؤولة", "start_date": "تاريخ البدء",
    "due_date": "تاريخ الاستحقاق", "priority": "الأولوية", "confidentiality": "مستوى السرية",
    "expected_result": "النتيجة المطلوبة", "success_indicator": "مؤشر النجاح", "notes": "ملاحظات",
    "requires_approval": "يتطلب اعتماد", "auto_progress": "احتساب الإنجاز من الفرعية",
}


# ===== أدوات مساعدة =====

def users_of(employees):
    return [e.user for e in employees if e is not None and e.user_id and e.user.is_active]


def task_team_users(task):
    emps = [a.employee for a in task.assignees.select_related("employee__user")]
    return users_of(emps)


def task_manager_users(task):
    emps = [task.unit.head, task.owner.manager]
    users = users_of(emps)
    if not users:
        users = list(User.objects.filter(role__code=RoleCode.ED_ASSISTANT, is_active=True))
    owner_user = task.owner.user if task.owner.user_id else None
    return [u for u in users if not owner_user or u.pk != owner_user.pk] or users


def role_users(code):
    return list(User.objects.filter(role__code=code, is_active=True))


def _touch(task):
    task.last_activity_at = timezone.now()
    task.flag_stale = False
    Task.objects.filter(pk=task.pk).update(last_activity_at=task.last_activity_at, flag_stale=False)


def _display(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    return str(value)


def _choice_display(task, field):
    getter = getattr(task, f"get_{field}_display", None)
    return getter() if getter else _display(getattr(task, field))


def _validate_dates(start, due):
    if start and due and due < start:
        raise ValidationError({"due_date": "تاريخ الاستحقاق يجب أن يكون بعد تاريخ البدء أو مساويًا له"})


# ===== إنشاء المهمة والإسناد =====

@transaction.atomic
def create_task(*, user, data, participants=(), participant_units=(), files=(), decision=None):
    """
    يدعم طرق الإسناد: موظف واحد، عدة موظفين، وحدة كاملة (يُسند لرئيسها)، عدة وحدات،
    مسؤول رئيسي + مشاركين، وحدة قائدة + وحدات مشاركة.
    """
    if not has_perm(user, "tasks.create") and not (decision and has_perm(user, "decisions.manage")):
        raise PermissionDenied("ليس لديك صلاحية إنشاء مهام")
    data = dict(data)
    unit = data.get("unit")
    if not unit:
        raise ValidationError({"unit": "الوحدة المسؤولة مطلوبة"})
    participants = [p for p in participants if p]
    if participants and not data.get("owner"):
        raise ValidationError({"owner": "لا يمكن إنشاء مهمة متعددة المشاركين بدون تحديد مسؤول رئيسي"})
    # الإسناد لوحدة كاملة دون تحديد موظف: يصبح رئيس الوحدة هو المسؤول الرئيسي
    owner = data.get("owner") or unit.head
    participants = [p for p in participants if p != owner]
    participant_units = [u for u in participant_units if u and u != unit]
    if not owner:
        raise ValidationError({"owner": "يجب تحديد مسؤول رئيسي (أو تعيين رئيس للوحدة المسؤولة)"})
    if not data.get("due_date"):
        raise ValidationError({"due_date": "تاريخ الاستحقاق مطلوب"})
    data["start_date"] = data.get("start_date") or timezone.localdate()
    _validate_dates(data["start_date"], data["due_date"])
    if not str(data.get("title", "")).strip():
        raise ValidationError({"title": "عنوان المهمة مطلوب"})
    if "requires_approval" not in data:
        data["requires_approval"] = bool(get_rules().get("require_approval", True))
    initial_progress = int(data.pop("progress", 0) or 0)
    if not 0 <= initial_progress <= 100:
        raise ValidationError({"progress": "نسبة الإنجاز بين 0 و 100"})
    data.pop("owner", None)

    task = Task.objects.create(**data, owner=owner, created_by=user, status=Status.NEW, last_activity_at=timezone.now())
    TaskAssignee.objects.create(task=task, employee=owner, role=AssigneeRole.PRIMARY, added_by=user)
    for emp in dict.fromkeys(participants):
        TaskAssignee.objects.create(task=task, employee=emp, role=AssigneeRole.PARTICIPANT, added_by=user)
    TaskUnit.objects.create(task=task, unit=unit, role=UnitRole.LEAD)
    for u in dict.fromkeys(participant_units):
        TaskUnit.objects.create(task=task, unit=u, role=UnitRole.PARTICIPANT)

    from .models import TaskStatusHistory

    TaskStatusHistory.objects.create(task=task, from_status="", to_status=Status.NEW, changed_by=user, note="إنشاء المهمة")
    audit.log("task.created", user=user, task=task, description=f"إنشاء المهمة «{task.title}»", new={
        "الوحدة": unit.name, "المسؤول الرئيسي": owner.full_name,
        "المشاركون": "، ".join(p.full_name for p in participants) or "—",
        "الوحدات المشاركة": "، ".join(u.name for u in participant_units) or "—",
        "تاريخ الاستحقاق": task.due_date, "الأولوية": task.get_priority_display(),
    })
    if decision is not None:
        from apps.meetings.models import DecisionTask

        DecisionTask.objects.create(decision=decision, task=task)
        audit.log("decision.converted", user=user, task=task, obj=decision,
                  description=f"مهمة ناتجة عن القرار رقم {decision.number}")
    for f in files:
        add_attachment(task, user, f)

    change_status(task, Status.ASSIGNED, user=user, note=f"تم الإسناد إلى {owner.full_name}")
    if initial_progress:
        task.progress = initial_progress
        task.save(update_fields=["progress"])
        if initial_progress < 100:
            change_status(task, Status.IN_PROGRESS, user=user, note="نسبة إنجاز أولية")

    notify(users_of([owner]), "task_assigned", f"أُسندت إليك مهمة جديدة: {task.title}",
           f"رقم المهمة {task.number} – الاستحقاق {task.due_date:%Y-%m-%d}", task=task, actor=user)
    notify(users_of(participants), "task_participant", f"أُضفت مشاركًا في المهمة: {task.title}",
           f"المسؤول الرئيسي: {owner.full_name}", task=task, actor=user)
    notify(users_of([u.head for u in participant_units]), "task_participant",
           f"وحدتكم مشاركة في المهمة: {task.title}", task=task, actor=user)
    if decision is not None:
        from apps.meetings.services import recalc_decision

        recalc_decision(decision)
    return task


@transaction.atomic
def update_task(task, *, user, data, participants=None, participant_units=None, owner=None):
    if not selectors.can_edit(user, task):
        raise PermissionDenied("ليس لديك صلاحية تعديل هذه المهمة")
    old, new = {}, {}
    _validate_dates(data.get("start_date", task.start_date), data.get("due_date", task.due_date))
    due_before = task.due_date
    unit_before = task.unit
    for field, value in data.items():
        if field not in TASK_EDITABLE_FIELDS:
            continue
        current = getattr(task, field)
        if current != value:
            old[TASK_EDITABLE_FIELDS[field]] = _choice_display(task, field) if field not in ("task_type", "unit") else _display(current)
            setattr(task, field, value)
            new[TASK_EDITABLE_FIELDS[field]] = _choice_display(task, field) if field not in ("task_type", "unit") else _display(value)
    task.save()
    if task.due_date != due_before:
        old.pop("تاريخ الاستحقاق", None)
        new.pop("تاريخ الاستحقاق", None)
        audit.log("task.due_changed", user=user, task=task, old={"تاريخ الاستحقاق": due_before}, new={"تاريخ الاستحقاق": task.due_date})
        if task.status == Status.OVERDUE and task.due_date >= timezone.localdate():
            change_status(task, Status.IN_PROGRESS, user=user, note="تمديد الموعد")
        TaskEscalation.objects.filter(task=task, resolved=False).update(resolved=True, resolved_at=timezone.now())
        Task.objects.filter(pk=task.pk).update(escalation_level=0)
        task.escalation_level = 0
    if old:
        audit.log("task.updated", user=user, task=task, old=old, new=new)
    if task.unit != unit_before:
        TaskUnit.objects.filter(task=task, role=UnitRole.LEAD).delete()
        TaskUnit.objects.filter(task=task, unit=task.unit).delete()
        TaskUnit.objects.create(task=task, unit=task.unit, role=UnitRole.LEAD)
    if owner is not None and owner != task.owner:
        change_owner(task, user=user, new_owner=owner)
    if participants is not None:
        set_participants(task, user=user, employees=participants)
    if participant_units is not None:
        set_participant_units(task, user=user, units=participant_units)
    _touch(task)
    return task


def change_owner(task, *, user, new_owner):
    old_owner = task.owner
    TaskAssignee.objects.filter(task=task, role=AssigneeRole.PRIMARY).delete()
    TaskAssignee.objects.filter(task=task, employee=new_owner).delete()
    TaskAssignee.objects.create(task=task, employee=new_owner, role=AssigneeRole.PRIMARY, added_by=user)
    task.owner = new_owner
    task.save(update_fields=["owner", "updated_at"])
    audit.log("task.owner_changed", user=user, task=task, old={"المسؤول الرئيسي": old_owner.full_name},
              new={"المسؤول الرئيسي": new_owner.full_name})
    notify(users_of([new_owner]), "task_assigned", f"أصبحت المسؤول الرئيسي عن المهمة: {task.title}", task=task, actor=user)
    notify(users_of([old_owner]), "owner_changed", f"تم تغيير مسؤول المهمة: {task.title}",
           f"المسؤول الجديد: {new_owner.full_name}", task=task, actor=user)


def set_participants(task, *, user, employees):
    wanted = {e.pk: e for e in employees if e and e.pk != task.owner_id}
    current = {a.employee_id: a for a in task.assignees.filter(role=AssigneeRole.PARTICIPANT).select_related("employee")}
    for pk, emp in wanted.items():
        if pk not in current:
            TaskAssignee.objects.create(task=task, employee=emp, role=AssigneeRole.PARTICIPANT, added_by=user)
            audit.log("task.participant_added", user=user, task=task, new={"مشارك": emp.full_name})
            notify(users_of([emp]), "task_participant", f"أُضفت مشاركًا في المهمة: {task.title}", task=task, actor=user)
    for pk, link in current.items():
        if pk not in wanted:
            link.delete()
            audit.log("task.participant_removed", user=user, task=task, old={"مشارك": link.employee.full_name})


def set_participant_units(task, *, user, units):
    wanted = {u.pk: u for u in units if u and u.pk != task.unit_id}
    current = {l.unit_id: l for l in task.task_units.filter(role=UnitRole.PARTICIPANT).select_related("unit")}
    for pk, unit in wanted.items():
        if pk not in current:
            TaskUnit.objects.create(task=task, unit=unit, role=UnitRole.PARTICIPANT)
            audit.log("task.unit_added", user=user, task=task, new={"وحدة مشاركة": unit.name})
            notify(users_of([unit.head]), "task_participant", f"وحدتكم مشاركة في المهمة: {task.title}", task=task, actor=user)
    for pk, link in current.items():
        if pk not in wanted:
            link.delete()
            audit.log("task.unit_removed", user=user, task=task, old={"وحدة مشاركة": link.unit.name})


# ===== المرفقات =====

def add_attachment(task, user, f, **links):
    kind = validate_upload(f)
    att = TaskAttachment.objects.create(
        task=task, file=f, original_name=f.name[:255], size=f.size, kind=kind, uploaded_by=user, **links,
    )
    audit.log("task.file_uploaded", user=user, task=task, obj=att, new={"الملف": att.original_name})
    _touch(task)
    return att


# ===== تحديث نسبة الإنجاز =====

@transaction.atomic
def update_progress(task, *, user, progress, comment, done_work, remaining_work="", update_date=None, files=(), _auto=False):
    if not _auto and not selectors.can_update_progress(user, task):
        raise PermissionDenied("لا يمكنك تحديث نسبة إنجاز هذه المهمة في حالتها الحالية")
    try:
        progress = int(progress)
    except (TypeError, ValueError):
        raise ValidationError({"progress": "نسبة الإنجاز يجب أن تكون رقمًا"})
    if not 0 <= progress <= 100:
        raise ValidationError({"progress": "نسبة الإنجاز يجب أن تكون بين 0 و 100"})
    if not (comment or "").strip():
        raise ValidationError({"comment": "تعليق التحديث مطلوب"})
    if not (done_work or "").strip():
        raise ValidationError({"done_work": "الأعمال المنجزة مطلوبة"})
    if not _auto and task.auto_progress and task.subtasks.exists():
        raise ValidationError({"progress": "نسبة الإنجاز تُحتسب تلقائيًا من المهام الفرعية لهذه المهمة"})
    before = task.progress
    upd = TaskUpdate.objects.create(
        task=task, user=user, progress_before=before, progress_after=progress, comment=comment,
        done_work=done_work, remaining_work=remaining_work or "", update_date=update_date or timezone.localdate(),
    )
    for f in files:
        add_attachment(task, user, f, update=upd)
    task.progress = progress
    task.save(update_fields=["progress", "updated_at"])
    _touch(task)
    audit.log("task.progress_changed", user=user, task=task, obj=upd, description=comment,
              old={"نسبة الإنجاز": f"{before}%"}, new={"نسبة الإنجاز": f"{progress}%"})
    if progress == 100:
        _complete(task, user)
    elif progress > 0 and task.status in (Status.ASSIGNED, Status.NEW, Status.RETURNED):
        change_status(task, Status.IN_PROGRESS, user=user, note="بدء التنفيذ")
    from apps.meetings.services import sync_task_decisions

    sync_task_decisions(task)
    return upd


def _complete(task, user):
    if task.status in (Status.PENDING_APPROVAL, Status.COMPLETED, Status.CLOSED):
        return
    if task.status == Status.NEW:
        change_status(task, Status.ASSIGNED, user=user)
    for ob in task.obstacles.filter(status__in=OPEN_OBSTACLE_STATUSES):
        ob.status = ObstacleStatus.RESOLVED
        ob.resolved_at = timezone.now()
        ob.save(update_fields=["status", "resolved_at"])
    TaskEscalation.objects.filter(task=task, resolved=False).update(resolved=True, resolved_at=timezone.now())
    Task.objects.filter(pk=task.pk).update(needs_ed_decision=False)
    if task.requires_approval:
        change_status(task, Status.PENDING_APPROVAL, user=user, note="اكتمال الإنجاز 100% – بانتظار الاعتماد")
        audit.log("task.approval_requested", user=user, task=task)
        notify(task_manager_users(task), "approval_requested", f"طلب اعتماد إنجاز المهمة: {task.title}",
               f"أكمل {task.owner.full_name} المهمة {task.number} بنسبة 100%", task=task, actor=user)
    else:
        change_status(task, Status.COMPLETED, user=user, note="اكتمال الإنجاز 100%")


# ===== الاعتماد والإعادة والإغلاق =====

def _require_approver(user, task):
    if not selectors.can_approve(user, task):
        raise PermissionDenied("ليس لديك صلاحية اعتماد هذه المهمة")


def _decision_comment(task, user, prefix, notes):
    if notes and notes.strip():
        TaskComment.objects.create(task=task, author=user, body=f"{prefix}: {notes.strip()}")


@transaction.atomic
def approve(task, *, user, notes=""):
    _require_approver(user, task)
    if task.status not in (Status.PENDING_APPROVAL, Status.COMPLETED):
        raise ValidationError("المهمة ليست بانتظار الاعتماد")
    task.approved_by = user
    task.approved_at = timezone.now()
    task.save(update_fields=["approved_by", "approved_at"])
    _decision_comment(task, user, "ملاحظات الاعتماد", notes)
    audit.log("task.approved", user=user, task=task, description=notes)
    change_status(task, Status.CLOSED, user=user, note=f"اعتماد الإنجاز{(' – ' + notes) if notes else ''}")
    audit.log("task.closed", user=user, task=task)
    notify(task_team_users(task), "task_approved", f"تم اعتماد إنجاز المهمة: {task.title}", notes, task=task, actor=user)
    notify(task_team_users(task), "task_closed", f"تم إغلاق المهمة: {task.title}", task=task, actor=user)
    return task


@transaction.atomic
def reject(task, *, user, notes):
    _require_approver(user, task)
    if task.status != Status.PENDING_APPROVAL:
        raise ValidationError("المهمة ليست بانتظار الاعتماد")
    if not (notes or "").strip():
        raise ValidationError({"notes": "سبب الرفض مطلوب"})
    _decision_comment(task, user, "سبب رفض الإنجاز", notes)
    audit.log("task.rejected", user=user, task=task, description=notes)
    change_status(task, Status.RETURNED, user=user, note=f"رفض الإنجاز – {notes}")
    notify(task_team_users(task), "approval_rejected", f"تم رفض إنجاز المهمة: {task.title}", notes, task=task, actor=user)
    return task


@transaction.atomic
def return_task(task, *, user, notes):
    _require_approver(user, task)
    if task.status not in (Status.PENDING_APPROVAL, Status.COMPLETED):
        raise ValidationError("لا يمكن إعادة المهمة إلا بعد اكتمالها أو أثناء انتظار الاعتماد")
    if not (notes or "").strip():
        raise ValidationError({"notes": "ملاحظات الإعادة مطلوبة"})
    _decision_comment(task, user, "ملاحظات إعادة التنفيذ", notes)
    audit.log("task.returned", user=user, task=task, description=notes)
    change_status(task, Status.RETURNED, user=user, note=f"إعادة للتنفيذ – {notes}")
    notify(task_team_users(task), "task_returned", f"أُعيدت المهمة للتنفيذ: {task.title}", notes, task=task, actor=user)
    return task


def transition(task, *, user, to, note=""):
    """تغيير يدوي للحالة ضمن الانتقالات المسموحة."""
    if not selectors.can_change_status(user, task):
        raise PermissionDenied("ليس لديك صلاحية تغيير حالة هذه المهمة")
    if to in MANAGER_TARGETS and not (has_perm(user, "tasks.cancel") and selectors.is_task_manager(user, task)):
        raise PermissionDenied("الإيقاف والإلغاء من صلاحيات المدير")
    if to == Status.CANCELLED and not (note or "").strip():
        raise ValidationError({"note": "سبب الإلغاء مطلوب"})
    change_status(task, to, user=user, note=note, via="manual")
    _touch(task)
    notify(task_team_users(task) + task_manager_users(task), "status_changed",
           f"تغيرت حالة المهمة «{task.title}» إلى {label(to)}", note, task=task, actor=user)
    return task


# ===== التعليقات والإشارات =====

MENTION_RE = re.compile(r"@\[([^\]]{2,150})\]")


def parse_mentions(body):
    names = set(MENTION_RE.findall(body or ""))
    emps = list(Employee.objects.filter(full_name__in=names))
    units = list(Unit.objects.filter(name__in=names))
    return emps, units


@transaction.atomic
def add_comment(task, *, user, body, parent=None, files=(), mention_employees=(), mention_units=(), obstacle=None):
    if not selectors.can_comment(user, task):
        raise PermissionDenied("لا يمكنك التعليق على هذه المهمة")
    body = (body or "").strip()
    if not body and not files:
        raise ValidationError({"body": "نص التعليق مطلوب"})
    if parent is not None and parent.task_id != task.pk:
        raise ValidationError("التعليق الأصلي لا يتبع هذه المهمة")
    comment = TaskComment.objects.create(task=task, author=user, body=body, parent=parent, obstacle=obstacle)
    emps, units = parse_mentions(body)
    emps = list({e.pk: e for e in list(emps) + list(mention_employees)}.values())
    units = list({u.pk: u for u in list(units) + list(mention_units)}.values())
    if emps:
        comment.mentioned_employees.set(emps)
    if units:
        comment.mentioned_units.set(units)
    for f in files:
        add_attachment(task, user, f, comment=comment)
    audit.log("task.comment_added", user=user, task=task, obj=comment, description=body[:300])
    _touch(task)

    mentioned_users = users_of(emps) + users_of([u.head for u in units])
    mentioned_ids = {u.pk for u in mentioned_users}
    notify(mentioned_users, "mentioned", f"أشار إليك {user.full_name} في المهمة: {task.title}", body[:200], task=task, actor=user)
    others = task_team_users(task) + task_manager_users(task)
    if parent is not None and parent.author:
        others.append(parent.author)
    notify([u for u in others if u.pk not in mentioned_ids], "comment_added",
           f"تعليق جديد من {user.full_name} على المهمة: {task.title}", body[:200], task=task, actor=user)
    return comment


# ===== العوائق والتعثر =====

@transaction.atomic
def register_obstacle(task, *, user, data, files=()):
    if not selectors.can_register_obstacle(user, task):
        raise PermissionDenied("لا يمكنك تسجيل عائق على هذه المهمة")
    if not (data.get("description") or "").strip():
        raise ValidationError({"description": "وصف المشكلة مطلوب"})
    obstacle = TaskObstacle.objects.create(task=task, created_by=user, previous_task_status=task.status, **data)
    for f in files:
        add_attachment(task, user, f, obstacle=obstacle)
    audit.log("task.obstacle_registered", user=user, task=task, obj=obstacle, description=obstacle.description,
              new={"نوع العائق": obstacle.get_obstacle_type_display(), "درجة التأثير": obstacle.get_impact_display(),
                   "يحتاج قرارًا إداريًا": "نعم" if obstacle.needs_admin_decision else "لا"})
    if get_rules().get("obstacle_sets_stalled", True) and task.status != Status.STALLED:
        change_status(task, Status.STALLED, user=user, note=f"تسجيل عائق: {obstacle.get_obstacle_type_display()}")
    if obstacle.needs_admin_decision:
        Task.objects.filter(pk=task.pk).update(needs_ed_decision=True)
        task.needs_ed_decision = True
    _touch(task)
    recipients = task_manager_users(task) + users_of([obstacle.intervener])
    if obstacle.needs_admin_decision:
        recipients += role_users(RoleCode.ED_ASSISTANT)
    notify(recipients, "obstacle_registered", f"تعثر في المهمة: {task.title}",
           f"{obstacle.get_obstacle_type_display()} – {obstacle.description[:150]}", task=task, actor=user)
    return obstacle


@transaction.atomic
def respond_obstacle(obstacle, *, user, response, resolve=False):
    if not selectors.can_respond_obstacle(user, obstacle):
        raise PermissionDenied("ليس لديك صلاحية الرد على هذا العائق")
    if not (response or "").strip():
        raise ValidationError({"response": "نص الرد مطلوب"})
    task = obstacle.task
    obstacle.response = response
    obstacle.responded_by = user
    obstacle.responded_at = timezone.now()
    obstacle.status = ObstacleStatus.RESOLVED if resolve else ObstacleStatus.RESPONDED
    if resolve:
        obstacle.resolved_at = timezone.now()
    obstacle.save()
    TaskComment.objects.create(task=task, author=user, body=f"رد على العائق ({obstacle.get_obstacle_type_display()}): {response}", obstacle=obstacle)
    audit.log("task.obstacle_responded", user=user, task=task, obj=obstacle, description=response)
    notify(task_team_users(task) + users_of([getattr(obstacle.created_by, "employee", None)]), "obstacle_responded",
           f"رد {user.full_name} على العائق في المهمة: {task.title}", response[:200], task=task, actor=user)
    if resolve:
        _after_obstacle_resolved(task, user)
    _touch(task)
    return obstacle


@transaction.atomic
def resolve_obstacle(obstacle, *, user, note=""):
    task = obstacle.task
    if not (selectors.is_involved(user, task) or selectors.can_respond_obstacle(user, obstacle)):
        raise PermissionDenied("ليس لديك صلاحية معالجة هذا العائق")
    obstacle.status = ObstacleStatus.RESOLVED
    obstacle.resolved_at = timezone.now()
    obstacle.save(update_fields=["status", "resolved_at"])
    audit.log("task.obstacle_resolved", user=user, task=task, obj=obstacle, description=note)
    _after_obstacle_resolved(task, user)
    _touch(task)
    return obstacle


def _after_obstacle_resolved(task, user):
    task.refresh_from_db()
    still_open = task.obstacles.filter(status__in=OPEN_OBSTACLE_STATUSES)
    if not still_open.filter(needs_admin_decision=True).exists():
        Task.objects.filter(pk=task.pk).update(needs_ed_decision=False)
    if task.status == Status.STALLED and not still_open.exists():
        target = Status.OVERDUE if task.due_date < timezone.localdate() else Status.IN_PROGRESS
        change_status(task, target, user=user, note="معالجة العائق واستئناف التنفيذ")


# ===== التصعيد اليدوي =====

LEVEL_TARGET_ROLE = {2: RoleCode.ED_ASSISTANT, 3: RoleCode.EXECUTIVE_DIRECTOR}


def escalation_recipients(task, level):
    if level == 1:
        return users_of([task.unit.head]) or role_users(RoleCode.ED_ASSISTANT)
    return role_users(LEVEL_TARGET_ROLE[level])


@transaction.atomic
def escalate(task, *, user, reason, level=None):
    if not selectors.can_escalate(user, task):
        raise PermissionDenied("ليس لديك صلاحية تصعيد هذه المهمة")
    if not (reason or "").strip():
        raise ValidationError({"reason": "سبب التصعيد مطلوب"})
    level = int(level or min(task.escalation_level + 1, 3))
    if level not in (1, 2, 3):
        raise ValidationError({"level": "مستوى تصعيد غير صالح"})
    recipients = escalation_recipients(task, level)
    for r in recipients:
        TaskEscalation.objects.create(task=task, kind="escalate", level=level, escalated_to=r, reason=reason,
                                      is_manual=True, created_by=user, due_date_snapshot=task.due_date)
    new_level = max(task.escalation_level, level)
    Task.objects.filter(pk=task.pk).update(escalation_level=new_level, needs_ed_decision=task.needs_ed_decision or level >= 3)
    task.escalation_level = new_level
    audit.log("task.escalated", user=user, task=task, description=reason,
              new={"مستوى التصعيد": ESCALATION_LEVEL_LABELS[level]})
    notify(recipients, "escalation", f"تصعيد المهمة: {task.title}", f"{user.full_name}: {reason}", task=task, actor=user)
    _touch(task)
    return task


# ===== المهام الفرعية =====

@transaction.atomic
def add_subtask(task, *, user, title, assignee=None, due_date=None, comment=""):
    if not (selectors.can_edit(user, task) or (selectors.is_involved(user, task) and task.is_open)):
        raise PermissionDenied("ليس لديك صلاحية إضافة مهام فرعية")
    if not (title or "").strip():
        raise ValidationError({"title": "عنوان المهمة الفرعية مطلوب"})
    if due_date and due_date > task.due_date:
        raise ValidationError({"due_date": "موعد المهمة الفرعية لا يتجاوز موعد المهمة الرئيسية"})
    sub = TaskSubtask.objects.create(task=task, title=title, assignee=assignee, due_date=due_date, comment=comment,
                                     created_by=user, sort_order=task.subtasks.count() + 1)
    audit.log("task.subtask_added", user=user, task=task, obj=sub, new={"مهمة فرعية": title,
              "المسؤول": assignee.full_name if assignee else "—"})
    if assignee:
        notify(users_of([assignee]), "task_assigned", f"أُسندت إليك مهمة فرعية: {title}",
               f"ضمن المهمة {task.number} – {task.title}", task=task, actor=user)
    _recalc_from_subtasks(task, user)
    return sub


@transaction.atomic
def update_subtask(sub, *, user, status=None, progress=None, comment=None, files=()):
    task = sub.task
    emp = selectors.employee_of(user)
    if not (selectors.can_update_progress(user, task) or (emp and sub.assignee_id == emp.pk)):
        raise PermissionDenied("ليس لديك صلاحية تحديث هذه المهمة الفرعية")
    old = {"الحالة": sub.get_status_display(), "النسبة": f"{sub.progress}%"}
    if progress is not None:
        progress = int(progress)
        if not 0 <= progress <= 100:
            raise ValidationError({"progress": "النسبة بين 0 و 100"})
        sub.progress = progress
        if progress == 100:
            sub.status = SubtaskStatus.COMPLETED
        elif progress > 0 and sub.status == SubtaskStatus.NEW:
            sub.status = SubtaskStatus.IN_PROGRESS
    if status:
        sub.status = status
        if status == SubtaskStatus.COMPLETED:
            sub.progress = 100
    if comment is not None:
        sub.comment = comment
    sub.save()
    for f in files:
        add_attachment(task, user, f, subtask=sub)
    audit.log("task.subtask_updated", user=user, task=task, obj=sub, description=sub.title, old=old,
              new={"الحالة": sub.get_status_display(), "النسبة": f"{sub.progress}%"})
    _touch(task)
    _recalc_from_subtasks(task, user)
    return sub


def _recalc_from_subtasks(task, user):
    task.refresh_from_db()
    if not task.auto_progress or not task.is_open or task.status in (Status.PENDING_APPROVAL, Status.ON_HOLD):
        return
    subs = list(task.subtasks.exclude(status=SubtaskStatus.CANCELLED))
    if not subs:
        return
    avg = round(sum(s.progress for s in subs) / len(subs))
    if avg != task.progress:
        update_progress(task, user=user, progress=avg, comment="احتساب تلقائي من المهام الفرعية",
                        done_work=f"اكتمل {sum(1 for s in subs if s.status == SubtaskStatus.COMPLETED)} من {len(subs)} مهام فرعية",
                        _auto=True)


def priority_label(code):
    return dict(Priority.choices).get(code, code)
