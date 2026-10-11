from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit import services as audit
from apps.audit.models import ACTIONS, AuditLog
from apps.notifications.events import EVENTS
from apps.tasks.constants import (
    MANUAL_TARGETS,
    PRIORITY_STYLE,
    PRIORITY_WEIGHT,
    STATUS_STYLE,
    TRANSITIONS,
    Priority,
    Status,
)
from apps.tasks.forms import EscalationRuleForm, TaskTypeForm
from apps.tasks.models import EscalationRule, TaskType

from .permissions import perm_required
from .settings_service import DEFAULTS, RULE_LABELS, get_setting, set_setting


@perm_required("settings.manage")
def statuses(request):
    labels = dict(Status.choices)
    rows = []
    for s in Status.values:
        rows.append({
            "code": s, "label": labels[s], "color": STATUS_STYLE[s][0], "icon": STATUS_STYLE[s][1],
            "targets": [(t, labels[t], t in MANUAL_TARGETS) for t in Status.values if t in TRANSITIONS[s]],
        })
    return render(request, "core/statuses.html", {"rows": rows})


@perm_required("settings.manage")
def priorities(request):
    rules = EscalationRule.objects.filter(is_active=True)
    rows = []
    for p, label in Priority.choices:
        specific = [r for r in rules if p in (r.priorities or [])]
        rows.append({"code": p, "label": label, "color": PRIORITY_STYLE[p], "weight": PRIORITY_WEIGHT[p],
                     "rules": specific or [r for r in rules if not r.priorities], "fast": bool(specific)})
    return render(request, "core/priorities.html", {"rows": rows})


@perm_required("settings.manage")
def task_types(request, pk=None):
    instance = get_object_or_404(TaskType, pk=pk) if pk else None
    form = TaskTypeForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        t = form.save()
        audit.log("settings.updated", description=f"نوع مهمة: {t.name}")
        messages.success(request, "تم حفظ نوع المهمة")
        return redirect("core:task_types")
    return render(request, "core/task_types.html", {"types": TaskType.objects.all(), "form": form, "instance": instance})


@perm_required("settings.manage")
def rules(request):
    current = get_setting("rules")
    defaults = DEFAULTS["rules"]
    if request.method == "POST":
        new = {}
        errors = []
        for key, default in defaults.items():
            if isinstance(default, bool):
                new[key] = request.POST.get(key) == "on"
            else:
                try:
                    val = int(request.POST.get(key, default))
                    if val < 0 or (key.endswith("_pct") and val > 100) or (key.endswith("_progress") and val > 100):
                        raise ValueError
                    new[key] = val
                except ValueError:
                    errors.append(RULE_LABELS.get(key, key))
        if errors:
            messages.error(request, "قيم غير صالحة: " + "، ".join(errors))
        else:
            set_setting("rules", new, request.user)
            audit.log("settings.updated", description="تعديل قواعد المتابعة", old=current, new=new)
            messages.success(request, "تم حفظ قواعد المتابعة؛ ستُطبق في التشغيل القادم للمحرك")
            return redirect("core:rules")
    fields = [{"key": k, "label": RULE_LABELS.get(k, k), "value": current.get(k, v), "is_bool": isinstance(v, bool)}
              for k, v in defaults.items()]
    return render(request, "core/rules.html", {"fields": fields})


@perm_required("settings.manage")
def escalation_rules(request, pk=None):
    instance = get_object_or_404(EscalationRule, pk=pk) if pk else None
    form = EscalationRuleForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        r = form.save()
        audit.log("settings.updated", description=f"قاعدة تصعيد: {r.name}")
        messages.success(request, "تم حفظ قاعدة التصعيد")
        return redirect("core:escalation_rules")
    return render(request, "core/escalation_rules.html", {"rules": EscalationRule.objects.all(), "form": form, "instance": instance})


@perm_required("settings.manage")
@require_POST
def escalation_rule_toggle(request, pk):
    r = get_object_or_404(EscalationRule, pk=pk)
    r.is_active = not r.is_active
    r.save(update_fields=["is_active"])
    audit.log("settings.updated", description=f"{'تفعيل' if r.is_active else 'تعطيل'} قاعدة تصعيد: {r.name}")
    return redirect("core:escalation_rules")


@perm_required("settings.manage")
def notification_settings(request):
    current = get_setting("notifications")
    channels = [("in_app", "داخل النظام", "bi-display"), ("email", "البريد الإلكتروني", "bi-envelope"), ("whatsapp", "WhatsApp", "bi-whatsapp")]
    if request.method == "POST":
        new = {code: {ch: request.POST.get(f"{code}__{ch}") == "on" for ch, _, _ in channels} for code in EVENTS}
        set_setting("notifications", new, request.user)
        audit.log("settings.updated", description="تعديل إعدادات التنبيهات")
        messages.success(request, "تم حفظ إعدادات التنبيهات")
        return redirect("core:notification_settings")
    from django.conf import settings as dj

    rows = [{"code": k, "label": v[0], "icon": v[1], "prefs": current.get(k, {})} for k, v in EVENTS.items()]
    return render(request, "core/notifications.html", {
        "rows": rows, "channels": channels,
        "email_ready": dj.EMAIL_NOTIFICATIONS_ENABLED, "whatsapp_ready": bool(dj.WHATSAPP_ENABLED and dj.WHATSAPP_API_URL),
    })


@perm_required("settings.manage")
def organization_settings(request):
    from django.core.exceptions import ValidationError

    from .branding import get_org, save_org
    from .settings_service import ORG_LABELS

    org = get_org()
    errors = {}
    if request.method == "POST":
        try:
            save_org(request.POST, user=request.user, logo=request.FILES.get("logo"),
                     remove_logo=request.POST.get("remove_logo") == "on")
            messages.success(request, "تم حفظ بيانات الجهة")
            return redirect("core:organization")
        except ValidationError as e:
            errors = e.message_dict if hasattr(e, "error_dict") else {"__all__": e.messages}
            org.update({k: request.POST.get(k, "") for k in ORG_LABELS})
    fields = [{"key": k, "label": label, "value": org.get(k, "")} for k, label in ORG_LABELS.items()]
    return render(request, "core/organization.html", {"fields": fields, "org": org, "errors": errors})


@perm_required("settings.manage")
def getting_started(request):
    from django.urls import reverse

    from apps.accounts.models import User
    from apps.meetings.models import MeetingDecision
    from apps.organization.models import Employee, Unit
    from apps.tasks.models import Task

    from .branding import get_org

    org = get_org()
    units = Unit.objects.filter(is_active=True)
    steps = [
        ("بيانات الجهة والشعار", "الاسم والشعار وبيانات التواصل تظهر في كل الصفحات والتقارير",
         bool(org.get("logo")), reverse("core:organization"), "bi-building"),
        ("الوحدات التنظيمية", f"{units.count()} وحدة – راجع الأسماء وأضف أو أوقف ما يلزم",
         units.exists(), reverse("organization:units"), "bi-diagram-3"),
        ("الموظفون وحساباتهم", f"{Employee.objects.count()} موظف – أضف يدويًا أو استورد من Excel",
         Employee.objects.count() > 1, reverse("organization:employee_import"), "bi-people"),
        ("رؤساء الوحدات", f"{units.filter(head__isnull=False).count()} من {units.count()} وحدة لها رئيس",
         units.exists() and not units.filter(head__isnull=True).exists(), reverse("organization:units"), "bi-person-badge"),
        ("مسؤولو النظام الإضافيون والمدير التنفيذي", f"{User.objects.filter(role__code__in=['admin', 'executive_director', 'ed_assistant']).count()} حساب إداري",
         User.objects.filter(role__code="executive_director").exists(), reverse("accounts:user_create"), "bi-shield-lock"),
        ("قواعد المتابعة والتصعيد", "راجع الحدود الزمنية وقواعد التصعيد بما يناسب الجمعية",
         None, reverse("core:escalation_rules"), "bi-sliders"),
        ("أول قرار أو مهمة", "سجّل قرار اجتماع وحوّله لمهام، أو أنشئ مهمة مباشرة",
         Task.objects.exists() or MeetingDecision.objects.exists(), reverse("tasks:create"), "bi-rocket-takeoff"),
    ]
    return render(request, "core/getting_started.html", {"steps": steps})


@perm_required("admin.audit")
def audit_log(request):
    qs = AuditLog.objects.select_related("user", "task")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(user__full_name__icontains=q) | Q(task__number__icontains=q))
    if request.GET.get("action"):
        qs = qs.filter(action=request.GET["action"])
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "core/audit.html", {"page_obj": page, "actions": sorted(ACTIONS.items(), key=lambda x: x[1])})
