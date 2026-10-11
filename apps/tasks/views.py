import logging
import mimetypes
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.core.permissions import has_perm, perm_required
from apps.meetings.models import MeetingDecision
from apps.organization.models import Employee, Unit

from . import selectors, services
from .constants import ACTIVE_STATUSES, OPEN_STATUSES, AssigneeRole, Status
from .forms import (
    CommentForm,
    EscalateForm,
    NotesForm,
    ObstacleForm,
    ObstacleResponseForm,
    ProgressForm,
    SubtaskForm,
    SubtaskUpdateForm,
    TaskFilterForm,
    TaskForm,
    TransitionForm,
)
from .models import Task, TaskAssignee, TaskAttachment, TaskComment, TaskObstacle, TaskSubtask
from .workflow import allowed_targets

logger = logging.getLogger("apps.tasks")

SORTS = {"due": "due_date", "-due": "-due_date", "priority": "-priority", "progress": "progress",
         "-progress": "-progress", "updated": "-last_activity_at", "new": "-created_at"}


def _errors(exc):
    if hasattr(exc, "message_dict"):
        return " ".join(m for msgs in exc.message_dict.values() for m in msgs)
    return " ".join(exc.messages)


def task_action(view):
    """غلاف موحد لإجراءات المهمة: جلب المهمة مع التحقق من الرؤية ومعالجة أخطاء طبقة الخدمات."""

    @wraps(view)
    @login_required
    @require_POST
    def wrapper(request, pk, *args, **kwargs):
        task = get_object_or_404(selectors.visible_tasks(request.user), pk=pk)
        try:
            result = view(request, task, *args, **kwargs)
        except ValidationError as e:
            messages.error(request, _errors(e))
            result = None
        except PermissionDenied as e:
            messages.error(request, str(e) or "غير مصرح لك بهذا الإجراء")
            result = None
        return result or redirect(request.POST.get("next") or task.get_absolute_url())

    return wrapper


# ===== القوائم والبحث =====

def apply_task_filters(qs, data):
    q = (data.get("q") or "").strip()
    if q:
        ids = Task.objects.filter(
            Q(number__icontains=q) | Q(title__icontains=q) | Q(description__icontains=q)
            | Q(owner__full_name__icontains=q) | Q(assignees__employee__full_name__icontains=q)
            | Q(unit__name__icontains=q) | Q(decisions__number__icontains=q)
            | Q(decisions__meeting__title__icontains=q) | Q(decisions__meeting__number__icontains=q)
            | Q(source_reference__icontains=q) | Q(project__icontains=q)
        ).values("pk")
        qs = qs.filter(pk__in=ids)
    if data.get("unit"):
        qs = qs.filter(pk__in=Task.objects.filter(Q(unit_id=data["unit"]) | Q(task_units__unit_id=data["unit"])).values("pk"))
    if data.get("employee"):
        qs = qs.filter(pk__in=Task.objects.filter(assignees__employee_id=data["employee"]).values("pk"))
    status = data.get("status")
    if status == "open":
        qs = qs.filter(status__in=OPEN_STATUSES)
    elif status:
        qs = qs.filter(status=status)
    for key, field in (("priority", "priority"), ("source", "source")):
        if data.get(key):
            qs = qs.filter(**{field: data[key]})
    if data.get("date_from"):
        qs = qs.filter(due_date__gte=data["date_from"])
    if data.get("date_to"):
        qs = qs.filter(due_date__lte=data["date_to"])
    if data.get("progress_min") not in (None, ""):
        qs = qs.filter(progress__gte=data["progress_min"])
    if data.get("progress_max") not in (None, ""):
        qs = qs.filter(progress__lte=data["progress_max"])
    flag = data.get("flag")
    if flag == "late":
        qs = qs.filter(status__in=ACTIVE_STATUSES, due_date__lt=timezone.localdate())
    elif flag == "followup":
        qs = qs.filter(flag_needs_followup=True)
    elif flag == "at_risk":
        qs = qs.filter(flag_at_risk=True)
    elif flag == "stale":
        qs = qs.filter(flag_stale=True)
    elif flag == "escalated":
        qs = qs.filter(escalation_level__gte=1)
    return qs


def with_people(qs):
    return qs.prefetch_related(
        Prefetch("assignees", queryset=TaskAssignee.objects.select_related("employee")),
        Prefetch("obstacles", queryset=TaskObstacle.objects.filter(status__in=["open", "responded"])),
    )


SCOPES = {
    "my": ("مهامي", "المهام المسندة إليك كمسؤول رئيسي أو مشارك"),
    "unit": ("مهام وحدتي", "جميع مهام الوحدة التي تتبع لها"),
    "all": ("جميع المهام", "كل المهام في الجمعية حسب صلاحياتك"),
}


@login_required
def task_list(request, scope="all"):
    if scope == "my":
        qs = selectors.my_tasks(request.user)
    elif scope == "unit":
        if not (has_perm(request.user, "tasks.view_unit") or selectors.employee_of(request.user)):
            raise PermissionDenied
        qs = selectors.unit_tasks(request.user)
    else:
        if not has_perm(request.user, "tasks.view_all"):
            raise PermissionDenied("ليس لديك صلاحية عرض جميع المهام")
        qs = selectors.visible_tasks(request.user)
    form = TaskFilterForm(request.GET or None)
    data = form.cleaned_data if form.is_valid() else {}
    data = {k: (v.pk if hasattr(v, "pk") else v) for k, v in data.items()}
    qs = apply_task_filters(qs, data)
    qs = with_people(qs.order_by(SORTS.get(request.GET.get("sort"), "due_date"), "-id"))
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    title, sub = SCOPES[scope]
    return render(request, "tasks/list.html", {
        "page_obj": page, "form": form, "scope": scope, "title": title, "sub": sub, "today": timezone.localdate(),
    })


@login_required
def search(request):
    q = request.GET.get("q", "").strip()
    tasks = selectors.visible_tasks(request.user)
    form = TaskFilterForm(request.GET or None)
    data = form.cleaned_data if form.is_valid() else {"q": q}
    data = {k: (v.pk if hasattr(v, "pk") else v) for k, v in data.items()}
    tasks = with_people(apply_task_filters(tasks, data).order_by("due_date"))
    page = Paginator(tasks, 20).get_page(request.GET.get("page"))
    decisions = MeetingDecision.objects.none()
    employees = Employee.objects.none()
    if q and has_perm(request.user, "decisions.view"):
        decisions = MeetingDecision.objects.select_related("meeting").filter(
            Q(number__icontains=q) | Q(text__icontains=q) | Q(meeting__title__icontains=q) | Q(meeting__number__icontains=q))[:10]
    if q and (has_perm(request.user, "tasks.view_all") or has_perm(request.user, "admin.employees")):
        employees = Employee.objects.filter(Q(full_name__icontains=q) | Q(employee_no__icontains=q))[:10]
    return render(request, "tasks/search.html", {"page_obj": page, "form": form, "q": q, "decisions": decisions,
                                                 "employees": employees, "today": timezone.localdate()})


@login_required
def mention_search(request):
    q = request.GET.get("q", "").strip()
    emps = Employee.objects.filter(status="active")
    units = Unit.objects.filter(is_active=True)
    if q:
        emps = emps.filter(full_name__icontains=q)
        units = units.filter(name__icontains=q)
    data = [{"type": "employee", "name": e.full_name, "sub": e.job_title} for e in emps[:8]]
    data += [{"type": "unit", "name": u.name, "sub": "وحدة"} for u in units[:5]]
    return JsonResponse(data, safe=False)


# ===== الإنشاء والتعديل =====

@perm_required("tasks.create")
def task_create(request):
    form = TaskForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            data = form.service_data()
            data["owner"] = form.cleaned_data.get("owner")
            task = services.create_task(
                user=request.user, data=data,
                participants=list(form.cleaned_data["participants"]),
                participant_units=list(form.cleaned_data["participant_units"]),
                files=form.cleaned_data.get("attachments") or [],
            )
            messages.success(request, f"تم إنشاء المهمة {task.number} وإرسال التنبيهات للمعنيين")
            return redirect(task.get_absolute_url())
        except ValidationError as e:
            messages.error(request, _errors(e))
    return render(request, "tasks/form.html", {"form": form})


@login_required
def task_edit(request, pk):
    task = get_object_or_404(selectors.visible_tasks(request.user), pk=pk)
    if not selectors.can_edit(request.user, task):
        raise PermissionDenied("ليس لديك صلاحية تعديل هذه المهمة")
    form = TaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        try:
            # إعادة تحميل نسخة نظيفة لأن ModelForm يعدّل instance أثناء التحقق
            fresh = Task.objects.get(pk=task.pk)
            services.update_task(
                fresh, user=request.user, data=form.service_data(),
                owner=form.cleaned_data.get("owner") or fresh.owner,
                participants=list(form.cleaned_data["participants"]),
                participant_units=list(form.cleaned_data["participant_units"]),
            )
            messages.success(request, "تم حفظ التعديلات وتسجيلها في سجل النشاط")
            return redirect(task.get_absolute_url())
        except ValidationError as e:
            messages.error(request, _errors(e))
    return render(request, "tasks/form.html", {"form": form, "task": task})


# ===== صفحة المهمة =====

TABS = [("details", "التفاصيل", "bi-info-circle"), ("subtasks", "المهام الفرعية", "bi-diagram-2"),
        ("updates", "التحديثات", "bi-graph-up"), ("comments", "المتابعة والردود", "bi-chat-square-text"),
        ("attachments", "المرفقات", "bi-paperclip"), ("obstacles", "العوائق", "bi-exclamation-octagon"),
        ("activity", "سجل النشاط", "bi-clock-history")]


@login_required
def task_detail(request, pk):
    task = get_object_or_404(
        selectors.visible_tasks(request.user).prefetch_related(
            Prefetch("assignees", queryset=TaskAssignee.objects.select_related("employee__user")),
            "task_units__unit"),
        pk=pk,
    )
    user = request.user
    comments = (TaskComment.objects.filter(task=task, parent__isnull=True)
                .select_related("author", "obstacle").prefetch_related("attachments", "replies__author", "replies__attachments"))
    obstacles = list(task.obstacles.select_related("intervener", "created_by", "responded_by", "task__unit", "task__owner")
                     .prefetch_related("attachments"))
    involved = selectors.is_involved(user, task)
    for o in obstacles:
        o.can_respond = o.is_open and selectors.can_respond_obstacle(user, o)
        o.can_resolve = o.is_open and (involved or o.can_respond)
    perms = {
        "edit": selectors.can_edit(user, task),
        "progress": selectors.can_update_progress(user, task),
        "comment": selectors.can_comment(user, task),
        "obstacle": selectors.can_register_obstacle(user, task),
        "approve": selectors.can_approve(user, task) and task.status in (Status.PENDING_APPROVAL, Status.COMPLETED),
        "escalate": selectors.can_escalate(user, task),
        "status": selectors.can_change_status(user, task),
        "subtask": selectors.can_edit(user, task) or (selectors.is_involved(user, task) and task.is_open),
        "manager": selectors.is_task_manager(user, task),
    }
    targets = allowed_targets(task) if perms["status"] else []
    if not (has_perm(user, "tasks.cancel") and perms["manager"]):
        targets = [t for t in targets if t not in (Status.ON_HOLD, Status.CANCELLED)]
    activity = AuditLog.objects.filter(task=task).select_related("user")
    tab = request.GET.get("tab", "details")
    ctx = {
        "task": task, "tab": tab, "tabs": TABS, "perms": perms,
        "comments": comments, "obstacles": obstacles,
        "updates": task.updates.select_related("user").prefetch_related("attachments"),
        "subtasks": task.subtasks.select_related("assignee").prefetch_related("attachments"),
        "attachments": task.attachments.select_related("uploaded_by"),
        "activity": activity, "status_history": task.status_history.select_related("changed_by"),
        "escalations": task.escalations.select_related("escalated_to", "rule")[:20],
        "decision": task.decision,
        "progress_form": ProgressForm(initial={"progress": task.progress}),
        "comment_form": CommentForm(), "obstacle_form": ObstacleForm(),
        "response_form": ObstacleResponseForm(), "notes_form": NotesForm(), "escalate_form": EscalateForm(),
        "transition_form": TransitionForm(targets=targets), "subtask_form": SubtaskForm(),
        "subtask_statuses": SubtaskUpdateForm.base_fields["status"].choices,
        "open_obstacles_count": sum(1 for o in obstacles if o.is_open),
        "user_employee": selectors.employee_of(user),
    }
    return render(request, "tasks/detail.html", ctx)


# ===== الإجراءات =====

@task_action
def action_progress(request, task):
    form = ProgressForm(request.POST, request.FILES)
    if not form.is_valid():
        raise ValidationError({k: v for k, v in form.errors.items()})
    d = form.cleaned_data
    services.update_progress(task, user=request.user, progress=d["progress"], comment=d["comment"],
                             done_work=d["done_work"], remaining_work=d["remaining_work"],
                             update_date=d["update_date"], files=d["attachments"])
    task.refresh_from_db()
    if task.status == Status.PENDING_APPROVAL:
        messages.success(request, "اكتمل الإنجاز 100% وانتقلت المهمة إلى «بانتظار الاعتماد» وأُرسل طلب الاعتماد")
    else:
        messages.success(request, f"تم تحديث نسبة الإنجاز إلى {task.progress}%")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=updates")


@task_action
def action_comment(request, task):
    form = CommentForm(request.POST, request.FILES)
    if not form.is_valid():
        raise ValidationError({k: v for k, v in form.errors.items()})
    parent = None
    if form.cleaned_data.get("parent"):
        parent = get_object_or_404(TaskComment, pk=form.cleaned_data["parent"], task=task)
    services.add_comment(task, user=request.user, body=form.cleaned_data["body"], parent=parent,
                         files=form.cleaned_data["attachments"])
    messages.success(request, "تم إضافة الرد")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=comments#comments-end")


@task_action
def action_upload(request, task):
    if not (selectors.is_involved(request.user, task) or selectors.is_task_manager(request.user, task)):
        raise PermissionDenied("لا يمكنك رفع ملفات على هذه المهمة")
    files = request.FILES.getlist("attachments")
    if not files:
        raise ValidationError("اختر ملفًا واحدًا على الأقل")
    for f in files:
        services.add_attachment(task, request.user, f)
    messages.success(request, f"تم رفع {len(files)} ملف")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=attachments")


@task_action
def action_obstacle(request, task):
    form = ObstacleForm(request.POST, request.FILES)
    if not form.is_valid():
        raise ValidationError({k: v for k, v in form.errors.items()})
    data = {k: v for k, v in form.cleaned_data.items() if k != "attachments"}
    services.register_obstacle(task, user=request.user, data=data, files=form.cleaned_data["attachments"])
    messages.warning(request, "تم تسجيل العائق وإبلاغ رئيس الوحدة والمعنيين")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=obstacles")


@task_action
def action_obstacle_respond(request, task, obstacle_id):
    obstacle = get_object_or_404(TaskObstacle, pk=obstacle_id, task=task)
    form = ObstacleResponseForm(request.POST)
    if not form.is_valid():
        raise ValidationError({k: v for k, v in form.errors.items()})
    services.respond_obstacle(obstacle, user=request.user, response=form.cleaned_data["response"],
                              resolve=form.cleaned_data["resolve"])
    messages.success(request, "تم إرسال الرد على العائق")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=obstacles")


@task_action
def action_obstacle_resolve(request, task, obstacle_id):
    obstacle = get_object_or_404(TaskObstacle, pk=obstacle_id, task=task)
    services.resolve_obstacle(obstacle, user=request.user, note=request.POST.get("note", ""))
    messages.success(request, "تم إغلاق العائق واستئناف التنفيذ")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=obstacles")


@task_action
def action_approve(request, task):
    services.approve(task, user=request.user, notes=request.POST.get("notes", ""))
    messages.success(request, "تم اعتماد الإنجاز وإغلاق المهمة")


@task_action
def action_reject(request, task):
    services.reject(task, user=request.user, notes=request.POST.get("notes", ""))
    messages.warning(request, "تم رفض الإنجاز وإعادة المهمة للمسؤول")


@task_action
def action_return(request, task):
    services.return_task(task, user=request.user, notes=request.POST.get("notes", ""))
    messages.warning(request, "تمت إعادة المهمة للتنفيذ")


@task_action
def action_transition(request, task):
    services.transition(task, user=request.user, to=request.POST.get("to"), note=request.POST.get("note", ""))
    messages.success(request, "تم تغيير الحالة")


@task_action
def action_escalate(request, task):
    services.escalate(task, user=request.user, reason=request.POST.get("reason", ""), level=request.POST.get("level") or None)
    messages.warning(request, "تم تصعيد المهمة وإبلاغ الجهة المختصة")


@task_action
def action_quick_reply(request, task):
    services.add_comment(task, user=request.user, body=request.POST.get("body", ""))
    messages.success(request, f"تم إرسال الرد على المهمة {task.number}")
    return redirect(request.POST.get("next") or task.get_absolute_url())


@task_action
def action_subtask_add(request, task):
    form = SubtaskForm(request.POST)
    if not form.is_valid():
        raise ValidationError({k: v for k, v in form.errors.items()})
    services.add_subtask(task, user=request.user, **form.cleaned_data)
    messages.success(request, "تمت إضافة المهمة الفرعية")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=subtasks")


@task_action
def action_subtask_update(request, task, sub_id):
    sub = get_object_or_404(TaskSubtask, pk=sub_id, task=task)
    form = SubtaskUpdateForm(request.POST, request.FILES)
    if not form.is_valid():
        raise ValidationError({k: v for k, v in form.errors.items()})
    d = form.cleaned_data
    services.update_subtask(sub, user=request.user, status=d["status"], progress=d["progress"], comment=d["comment"],
                            files=d["attachments"])
    messages.success(request, "تم تحديث المهمة الفرعية")
    return redirect(reverse("tasks:detail", args=[task.pk]) + "?tab=subtasks")


@login_required
def attachment_download(request, pk):
    """تنزيل محمي: لا يُخدم الملف إلا لمن يحق له رؤية المهمة."""
    att = get_object_or_404(TaskAttachment.objects.select_related("task"), pk=pk)
    if not selectors.can_view(request.user, att.task):
        raise Http404
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404("الملف غير موجود")
    content_type = mimetypes.guess_type(att.original_name)[0] or "application/octet-stream"
    inline = att.kind in ("image", "pdf") and request.GET.get("inline")
    resp = FileResponse(fh, as_attachment=not inline, filename=att.original_name, content_type=content_type)
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
