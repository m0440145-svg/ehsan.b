"""
محرك القواعد (Rule Engine) ومحرك التصعيد (Escalation Engine).
- يقيّم كل مهمة مفتوحة وفق القواعد القابلة للتعديل من الإعدادات.
- يحوّل الحالة إلى «متأخرة» عند تجاوز الاستحقاق.
- يطبق قواعد التصعيد مرة واحدة لكل (مهمة، قاعدة، موعد استحقاق).
يشغَّل تلقائيًا كل N دقيقة، أو عبر: python manage.py run_task_engine
"""
import logging

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.core.permissions import RoleCode
from apps.core.settings_service import get_rules, set_setting
from apps.notifications.services import notify

from .constants import ACTIVE_STATUSES, OPEN_STATUSES, EscalationTarget, Status
from .models import EscalationRule, Task, TaskEscalation
from .services import users_of
from .workflow import change_status

logger = logging.getLogger("apps.tasks.engine")

AUTO_OVERDUE_FROM = {Status.NEW, Status.ASSIGNED, Status.IN_PROGRESS, Status.RETURNED}


def evaluate_flags(task, rules, today, now):
    active = task.status in ACTIVE_STATUSES
    total_days = max((task.due_date - task.start_date).days, 1)
    elapsed_pct = (today - task.start_date).days / total_days * 100
    return {
        "flag_needs_followup": active and elapsed_pct > rules["followup_elapsed_pct"] and task.progress <= rules["followup_max_progress"],
        "flag_at_risk": active and elapsed_pct >= rules["at_risk_elapsed_pct"] and task.progress < rules["at_risk_max_progress"],
        "flag_stale": active and (now - task.last_activity_at).days >= rules["stale_days"],
    }


def run_engine(now=None):
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    rules = get_rules()
    stats = {"evaluated": 0, "flags_changed": 0, "marked_overdue": 0, "escalations": 0, "notifications": 0}
    tasks = Task.objects.filter(status__in=OPEN_STATUSES).select_related("unit__head__user", "owner__user", "owner__manager__user")
    for task in tasks:
        stats["evaluated"] += 1
        flags = evaluate_flags(task, rules, today, now)
        changed = {k: v for k, v in flags.items() if getattr(task, k) != v}
        if changed:
            Task.objects.filter(pk=task.pk).update(**changed)
            for k, v in changed.items():
                setattr(task, k, v)
            stats["flags_changed"] += 1
        with transaction.atomic():
            if rules.get("auto_overdue", True) and task.status in AUTO_OVERDUE_FROM and task.due_date < today:
                change_status(task, Status.OVERDUE, note="تحويل تلقائي: تجاوز تاريخ الاستحقاق دون اكتمال", via="system")
                stats["marked_overdue"] += 1
            elif task.status == Status.OVERDUE and task.due_date >= today:
                change_status(task, Status.IN_PROGRESS, note="تحويل تلقائي: الموعد الجديد لم يحن بعد", via="system")
    esc, notes = run_escalations(today)
    stats["escalations"] = esc
    stats["notifications"] = notes
    set_setting("engine_state", {"last_run": now.isoformat(), "last_stats": stats})
    logger.info("تشغيل محرك القواعد: %s", stats)
    return stats


def resolve_targets(task, targets):
    users = []
    for t in targets:
        if t == EscalationTarget.OWNER:
            users += users_of([task.owner])
        elif t == EscalationTarget.PARTICIPANTS:
            users += users_of(task.participants)
        elif t == EscalationTarget.UNIT_HEAD:
            users += users_of([task.unit.head])
        elif t == EscalationTarget.ED_ASSISTANT:
            users += list(User.objects.filter(role__code=RoleCode.ED_ASSISTANT, is_active=True))
        elif t == EscalationTarget.EXECUTIVE_DIRECTOR:
            users += list(User.objects.filter(role__code=RoleCode.EXECUTIVE_DIRECTOR, is_active=True))
    return list({u.pk: u for u in users}.values())


def rule_matches(rule, days_to_due):
    if rule.trigger == EscalationRule.Trigger.BEFORE_DUE:
        return 0 < days_to_due <= rule.days
    if rule.trigger == EscalationRule.Trigger.ON_DUE:
        return days_to_due == 0
    if rule.trigger == EscalationRule.Trigger.AFTER_DUE:
        return -days_to_due >= max(rule.days, 1)
    return False


def _rules_for(task, rules):
    """القواعد الخاصة بأولوية المهمة تتقدم على العامة (مثل التصعيد الأسرع للحرجة)."""
    specific = [r for r in rules if r.priorities and task.priority in r.priorities]
    if specific:
        return specific
    return [r for r in rules if not r.priorities]


def run_escalations(today):
    rules = list(EscalationRule.objects.filter(is_active=True))
    escalations = notifications = 0
    if not rules:
        return 0, 0
    tasks = Task.objects.filter(status__in=ACTIVE_STATUSES).select_related("unit__head__user", "owner__user")
    for task in tasks:
        days_to_due = (task.due_date - today).days
        for rule in _rules_for(task, rules):
            if not rule_matches(rule, days_to_due):
                continue
            if TaskEscalation.objects.filter(task=task, rule=rule, due_date_snapshot=task.due_date).exists():
                continue
            recipients = resolve_targets(task, rule.targets)
            with transaction.atomic():
                for r in recipients or [None]:
                    TaskEscalation.objects.create(task=task, rule=rule, kind=rule.action, level=rule.level,
                                                  escalated_to=r, reason=rule.name, due_date_snapshot=task.due_date)
                if rule.action == EscalationRule.Action.ESCALATE:
                    escalations += 1
                    level = max(task.escalation_level, rule.level)
                    Task.objects.filter(pk=task.pk).update(escalation_level=level)
                    task.escalation_level = level
                    audit.log("task.escalated", task=task, system=True, description=f"تصعيد آلي: {rule.name}")
                    notify(recipients, "escalation", f"تصعيد آلي للمهمة: {task.title}",
                           f"{rule.name} – متأخرة {max(0, -days_to_due)} يوم", task=task)
                else:
                    event = "due_soon" if days_to_due > 0 else ("due_today" if days_to_due == 0 else "overdue")
                    text = {"due_soon": f"تستحق خلال {days_to_due} يوم", "due_today": "تستحق اليوم",
                            "overdue": f"متأخرة {-days_to_due} يوم"}[event]
                    notify(recipients, event, f"{text}: {task.title}", rule.name, task=task)
                notifications += len(recipients)
    return escalations, notifications


DEFAULT_ESCALATION_RULES = [
    # (الاسم، المشغل، الأيام، الإجراء، المستهدفون، المستوى، الأولويات)
    ("تنبيه قبل الاستحقاق بـ3 أيام", "before_due", 3, "notify", ["owner", "participants"], 0, []),
    ("تنبيه في يوم الاستحقاق", "on_due", 0, "notify", ["owner", "unit_head"], 0, []),
    ("تصعيد لرئيس الوحدة بعد يوم من التأخير", "after_due", 1, "escalate", ["unit_head", "owner"], 1, []),
    ("تصعيد لمساعد المدير التنفيذي بعد 3 أيام", "after_due", 3, "escalate", ["ed_assistant", "unit_head"], 2, []),
    ("تصعيد للمدير التنفيذي بعد 7 أيام", "after_due", 7, "escalate", ["executive_director", "ed_assistant"], 3, []),
    # تصعيد أسرع للمهام الحرجة
    ("الحرجة: تنبيه قبل الاستحقاق بـ5 أيام", "before_due", 5, "notify", ["owner", "participants", "unit_head"], 0, ["critical"]),
    ("الحرجة: تنبيه في يوم الاستحقاق", "on_due", 0, "notify", ["owner", "unit_head", "ed_assistant"], 0, ["critical"]),
    ("الحرجة: تصعيد لمساعد المدير التنفيذي بعد يوم", "after_due", 1, "escalate", ["unit_head", "ed_assistant"], 2, ["critical"]),
    ("الحرجة: تصعيد للمدير التنفيذي بعد يومين", "after_due", 2, "escalate", ["executive_director"], 3, ["critical"]),
]


def ensure_default_rules():
    if EscalationRule.objects.exists():
        return
    for i, (name, trig, days, action, targets, level, prios) in enumerate(DEFAULT_ESCALATION_RULES, 1):
        EscalationRule.objects.create(name=name, trigger=trig, days=days, action=action, targets=targets,
                                      level=level, priorities=prios, sort_order=i)
