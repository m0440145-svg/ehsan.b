"""أحداث التنبيهات (بدون استيراد نماذج لتجنب الدوائر)."""

EVENTS = {
    "task_assigned": ("إسناد مهمة جديدة", "bi-person-check", "primary"),
    "task_participant": ("إضافتك مشاركًا في مهمة", "bi-people", "primary"),
    "owner_changed": ("تغيير المسؤول", "bi-arrow-left-right", "warning"),
    "comment_added": ("تعليق جديد", "bi-chat-dots", "info"),
    "mentioned": ("تمت الإشارة إليك", "bi-at", "info"),
    "due_soon": ("اقتراب موعد الاستحقاق", "bi-hourglass-split", "warning"),
    "due_today": ("تستحق اليوم", "bi-calendar-event", "warning"),
    "overdue": ("انتهاء الموعد", "bi-alarm", "danger"),
    "obstacle_registered": ("تسجيل تعثر", "bi-exclamation-octagon", "danger"),
    "obstacle_responded": ("رد على عائق", "bi-reply", "info"),
    "approval_requested": ("طلب اعتماد", "bi-patch-question", "purple"),
    "approval_rejected": ("رفض الاعتماد", "bi-x-octagon", "danger"),
    "task_approved": ("اعتماد الإنجاز", "bi-patch-check", "success"),
    "task_returned": ("إعادة المهمة", "bi-arrow-counterclockwise", "warning"),
    "task_closed": ("إغلاق المهمة", "bi-lock", "success"),
    "escalation": ("تصعيد", "bi-graph-up-arrow", "danger"),
    "status_changed": ("تغيير الحالة", "bi-arrow-repeat", "secondary"),
    "decision_assigned": ("متابعة قرار", "bi-journal-check", "primary"),
}


def event_label(code):
    return EVENTS.get(code, (code,))[0]
