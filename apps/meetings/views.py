import mimetypes
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit import services as audit
from apps.core.permissions import has_perm, perm_required
from apps.organization.models import Employee, Unit
from apps.tasks import selectors
from apps.tasks.constants import ACTIVE_STATUSES, DONE_STATUSES, Priority
from apps.tasks.views import with_people

from . import services
from .forms import COMMITTEE_CHOICES, DecisionForm, MeetingForm
from .models import DecisionAttachment, Meeting, MeetingDecision


@perm_required("decisions.view")
def meetings_list(request):
    qs = Meeting.objects.annotate(n=Count("decisions")).order_by("-date")
    form = MeetingForm(request.POST or None)
    if request.method == "POST":
        if not has_perm(request.user, "decisions.manage"):
            raise PermissionDenied
        if form.is_valid():
            m = form.save(commit=False)
            m.created_by = request.user
            m.save()
            audit.log("meeting.created", obj=m, description=f"{m.number} – {m.title}")
            messages.success(request, "تم إضافة الاجتماع")
            return redirect("meetings:meetings")
    return render(request, "meetings/meetings.html", {"meetings": qs, "form": form, "committees": COMMITTEE_CHOICES})


@perm_required("decisions.view")
def decisions_list(request):
    qs = MeetingDecision.objects.select_related("meeting", "followup_owner").annotate(task_count=Count("tasks"))
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(text__icontains=q) | Q(meeting__title__icontains=q) | Q(meeting__number__icontains=q))
    if request.GET.get("meeting"):
        qs = qs.filter(meeting_id=request.GET["meeting"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("committee"):
        qs = qs.filter(meeting__committee=request.GET["committee"])
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "meetings/decisions.html", {
        "page_obj": page, "meetings": Meeting.objects.all(), "statuses": MeetingDecision.Status.choices,
        "committees": Meeting.objects.values_list("committee", flat=True).distinct(),
    })


@perm_required("decisions.manage")
def decision_create(request):
    form = DecisionForm(request.POST or None, request.FILES or None, initial={"meeting": request.GET.get("meeting")})
    if request.method == "POST" and form.is_valid():
        data = {k: v for k, v in form.cleaned_data.items() if k != "attachments"}
        try:
            d = services.create_decision(user=request.user, data=data, files=form.cleaned_data["attachments"])
            messages.success(request, f"تم تسجيل القرار {d.number}")
            return redirect(d.get_absolute_url())
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
    return render(request, "meetings/decision_form.html", {"form": form})


@perm_required("decisions.view")
def decision_detail(request, pk):
    d = get_object_or_404(MeetingDecision.objects.select_related("meeting", "followup_owner"), pk=pk)
    visible = selectors.visible_tasks(request.user)
    tasks = with_people(visible.filter(pk__in=d.tasks.values("pk")).order_by("due_date"))
    hidden = d.tasks.count() - tasks.count()
    today = timezone.localdate()
    all_tasks = list(d.tasks.all())
    stats = {
        "total": len(all_tasks),
        "done": sum(1 for t in all_tasks if t.status in DONE_STATUSES),
        "late": sum(1 for t in all_tasks if t.status in ACTIVE_STATUSES and t.due_date < today),
        "stalled": sum(1 for t in all_tasks if t.status == "stalled"),
    }
    return render(request, "meetings/decision_detail.html", {"d": d, "tasks": tasks, "hidden": hidden, "stats": stats})


def _parse_rows(request):
    """قراءة صفوف المهام الناتجة من نموذج التحويل مع التحقق من كل حقل."""
    try:
        count = min(int(request.POST.get("rows", 0)), 30)
    except ValueError:
        count = 0
    items, errors = [], []
    units = {str(u.pk): u for u in Unit.objects.filter(is_active=True)}
    emps = {str(e.pk): e for e in Employee.objects.all()}
    for i in range(count + 5):
        title = request.POST.get(f"title_{i}")
        if title is None:
            continue
        n = len(items) + 1
        unit = units.get(request.POST.get(f"unit_{i}", ""))
        owner = emps.get(request.POST.get(f"owner_{i}", ""))
        participants = [emps[p] for p in request.POST.getlist(f"participants_{i}") if p in emps]
        due_raw = request.POST.get(f"due_date_{i}", "")
        priority = request.POST.get(f"priority_{i}") or Priority.NORMAL
        try:
            due = date.fromisoformat(due_raw)
        except ValueError:
            due = None
        if not unit:
            errors.append(f"المهمة {n}: اختر الوحدة")
        if not due:
            errors.append(f"المهمة {n}: تاريخ الاستحقاق مطلوب")
        elif due < timezone.localdate():
            errors.append(f"المهمة {n}: تاريخ الاستحقاق في الماضي")
        if participants and not owner:
            errors.append(f"المهمة {n}: حدد المسؤول الرئيسي لوجود مشاركين")
        if unit and not owner and not unit.head_id:
            errors.append(f"المهمة {n}: الوحدة بلا رئيس، حدد المسؤول")
        if priority not in Priority.values:
            priority = Priority.NORMAL
        items.append({"title": title.strip(), "unit": unit, "owner": owner, "participants": participants,
                      "due_date": due, "priority": priority})
    if not items:
        errors.append("أضف مهمة واحدة على الأقل")
    return items, errors


@perm_required("decisions.manage")
def decision_convert(request, pk):
    d = get_object_or_404(MeetingDecision.objects.select_related("meeting"), pk=pk)
    if request.method == "POST":
        items, errors = _parse_rows(request)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            try:
                created = services.convert_to_tasks(d, user=request.user, items=items)
                messages.success(request, f"تم إنشاء {len(created)} مهمة مرتبطة بالقرار {d.number} وإرسال التنبيهات")
                return redirect(d.get_absolute_url())
            except (ValidationError, PermissionDenied) as e:
                messages.error(request, " ".join(getattr(e, "messages", [str(e)])))
    return render(request, "meetings/convert.html", {
        "d": d, "units": Unit.objects.filter(is_active=True), "employees": Employee.objects.filter(status="active").order_by("full_name"),
        "priorities": Priority.choices, "default_due": d.due_date,
    })


@perm_required("decisions.view")
def tracking(request):
    today = timezone.localdate()
    qs = MeetingDecision.objects.select_related("meeting", "followup_owner").prefetch_related("tasks").order_by("-decision_date")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("meeting"):
        qs = qs.filter(meeting_id=request.GET["meeting"])
    rows = []
    for d in qs:
        tasks = [t for t in d.tasks.all() if t.status != "cancelled"]
        rows.append({
            "d": d, "total": len(tasks),
            "done": sum(1 for t in tasks if t.status in DONE_STATUSES),
            "late": sum(1 for t in tasks if t.status in ACTIVE_STATUSES and t.due_date < today),
            "stalled": sum(1 for t in tasks if t.status == "stalled"),
        })
    summary = {
        "decisions": len(rows), "implemented": sum(1 for r in rows if r["d"].status == "implemented"),
        "without_tasks": sum(1 for r in rows if r["total"] == 0),
        "avg": round(sum(r["d"].implementation_pct for r in rows) / len(rows)) if rows else 0,
    }
    return render(request, "meetings/tracking.html", {"rows": rows, "summary": summary, "meetings": Meeting.objects.all(),
                                                      "statuses": MeetingDecision.Status.choices})


@perm_required("decisions.view")
def decision_attachment(request, pk):
    att = get_object_or_404(DecisionAttachment, pk=pk)
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404
    ct = mimetypes.guess_type(att.original_name)[0] or "application/octet-stream"
    return FileResponse(fh, as_attachment=True, filename=att.original_name, content_type=ct)
