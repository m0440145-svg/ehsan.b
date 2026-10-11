"""خدمة الإعدادات: قيم افتراضية مدمجة مع ما يحفظه المسؤول في قاعدة البيانات."""
import copy

from django.core.cache import cache

from apps.notifications.events import EVENTS

DEFAULTS = {
    "rules": {
        # إذا مر أكثر من X% من المدة والإنجاز <= Y% => بحاجة متابعة
        "followup_elapsed_pct": 30,
        "followup_max_progress": 0,
        # إذا مر X% من المدة والإنجاز < Y% => مرشحة للتعثر
        "at_risk_elapsed_pct": 70,
        "at_risk_max_progress": 30,
        # عدد أيام بدون تحديث
        "stale_days": 5,
        # تحويل الحالة تلقائيًا إلى متأخرة بعد الاستحقاق
        "auto_overdue": True,
        # تسجيل عائق يحول الحالة إلى متعثرة
        "obstacle_sets_stalled": True,
        # نافذة "تستحق قريبًا"
        "due_soon_days": 3,
        # المتأخرة لفترة طويلة
        "overdue_long_days": 7,
        # الاعتماد مطلوب افتراضيًا للمهام الجديدة
        "require_approval": True,
        # الفاصل الزمني لتشغيل المحرك تلقائيًا (دقائق)
        "engine_interval_minutes": 10,
    },
    "notifications": {
        code: {"in_app": True, "email": False, "whatsapp": False} for code in EVENTS
    },
    "engine_state": {"last_run": None, "last_stats": {}},
}

RULE_LABELS = {
    "followup_elapsed_pct": "نسبة المدة المنقضية لاعتبار المهمة «بحاجة متابعة» (%)",
    "followup_max_progress": "الحد الأعلى للإنجاز لاعتبارها «بحاجة متابعة» (%)",
    "at_risk_elapsed_pct": "نسبة المدة المنقضية لاعتبار المهمة «مرشحة للتعثر» (%)",
    "at_risk_max_progress": "إذا كان الإنجاز أقل من (%) تعتبر «مرشحة للتعثر»",
    "stale_days": "عدد الأيام دون تحديث لإظهار تنبيه «بدون تحديث»",
    "auto_overdue": "تحويل الحالة تلقائيًا إلى «متأخرة» بعد تجاوز الاستحقاق",
    "obstacle_sets_stalled": "تسجيل عائق يحوّل المهمة إلى «متعثرة»",
    "due_soon_days": "عدد أيام نافذة «تستحق قريبًا»",
    "overdue_long_days": "عدد أيام التأخير لاعتبارها «متأخرة لفترة طويلة»",
    "require_approval": "اشتراط الاعتماد عند الوصول إلى 100% (افتراضي للمهام الجديدة)",
    "engine_interval_minutes": "الفاصل الزمني لتشغيل محرك القواعد تلقائيًا (دقائق)",
}

_CACHE_PREFIX = "sysset:"


def get_setting(key):
    cached = cache.get(_CACHE_PREFIX + key)
    if cached is not None:
        return copy.deepcopy(cached)
    from .models import SystemSetting

    value = copy.deepcopy(DEFAULTS.get(key, {}))
    row = SystemSetting.objects.filter(key=key).first()
    if row and isinstance(row.value, dict):
        for k, v in row.value.items():
            if isinstance(v, dict) and isinstance(value.get(k), dict):
                value[k].update(v)
            else:
                value[k] = v
    cache.set(_CACHE_PREFIX + key, value, 60)
    return copy.deepcopy(value)


def set_setting(key, value, user=None):
    from .models import SystemSetting

    SystemSetting.objects.update_or_create(key=key, defaults={"value": value, "updated_by": user})
    cache.delete(_CACHE_PREFIX + key)


def get_rules():
    return get_setting("rules")
