from django.db import models


class Status(models.TextChoices):
    NEW = "new", "جديدة"
    ASSIGNED = "assigned", "تم الإسناد"
    IN_PROGRESS = "in_progress", "قيد التنفيذ"
    WAITING_REPLY = "waiting_reply", "بانتظار رد"
    WAITING_EXTERNAL = "waiting_external", "بانتظار جهة خارجية"
    STALLED = "stalled", "متعثرة"
    OVERDUE = "overdue", "متأخرة"
    COMPLETED = "completed", "مكتملة"
    PENDING_APPROVAL = "pending_approval", "بانتظار الاعتماد"
    RETURNED = "returned", "معادة للتنفيذ"
    ON_HOLD = "on_hold", "موقوفة"
    CANCELLED = "cancelled", "ملغاة"
    CLOSED = "closed", "مغلقة"


S = Status

# المهام المنجزة
DONE_STATUSES = {S.COMPLETED, S.CLOSED}
# المهام المنتهية (لا تحتسب مفتوحة)
TERMINAL_STATUSES = {S.COMPLETED, S.CLOSED, S.CANCELLED}
OPEN_STATUSES = [s for s in S.values if s not in TERMINAL_STATUSES]
# المهام التي ما زال العمل عليها جاريًا (يمكن أن تتأخر)
ACTIVE_STATUSES = [s for s in OPEN_STATUSES if s not in (S.PENDING_APPROVAL, S.ON_HOLD)]

# ===== سير العمل: الانتقالات المسموحة =====
_WORKING = {S.IN_PROGRESS, S.WAITING_REPLY, S.WAITING_EXTERNAL, S.STALLED, S.ON_HOLD, S.CANCELLED,
            S.PENDING_APPROVAL, S.COMPLETED, S.OVERDUE}
TRANSITIONS = {
    S.NEW: {S.ASSIGNED, S.IN_PROGRESS, S.ON_HOLD, S.CANCELLED},
    S.ASSIGNED: _WORKING,
    S.IN_PROGRESS: _WORKING - {S.IN_PROGRESS},
    S.WAITING_REPLY: _WORKING - {S.WAITING_REPLY},
    S.WAITING_EXTERNAL: _WORKING - {S.WAITING_EXTERNAL},
    S.STALLED: _WORKING - {S.STALLED},
    S.OVERDUE: _WORKING - {S.OVERDUE},
    S.RETURNED: _WORKING,
    S.PENDING_APPROVAL: {S.CLOSED, S.RETURNED},
    S.COMPLETED: {S.CLOSED, S.RETURNED},
    S.ON_HOLD: {S.IN_PROGRESS, S.ASSIGNED, S.CANCELLED, S.OVERDUE},
    S.CANCELLED: set(),
    S.CLOSED: set(),
}

# الحالات التي يختارها المستخدم يدويًا (البقية تتم عبر إجراءات: نسبة 100%، اعتماد، إعادة، تعثر، محرك القواعد)
MANUAL_TARGETS = {S.IN_PROGRESS, S.WAITING_REPLY, S.WAITING_EXTERNAL, S.ON_HOLD, S.CANCELLED}
# الحالات التي تحتاج صلاحية إدارية للانتقال إليها يدويًا
MANAGER_TARGETS = {S.ON_HOLD, S.CANCELLED}

STATUS_STYLE = {
    S.NEW: ("#6c757d", "bi-plus-circle"),
    S.ASSIGNED: ("#0d6efd", "bi-person-check"),
    S.IN_PROGRESS: ("#1c6dd0", "bi-play-circle"),
    S.WAITING_REPLY: ("#e0a800", "bi-chat-left-dots"),
    S.WAITING_EXTERNAL: ("#c99700", "bi-building"),
    S.STALLED: ("#8b1a1a", "bi-exclamation-octagon"),
    S.OVERDUE: ("#dc3545", "bi-alarm"),
    S.COMPLETED: ("#198754", "bi-check-circle"),
    S.PENDING_APPROVAL: ("#6f42c1", "bi-patch-question"),
    S.RETURNED: ("#cf6028", "bi-arrow-counterclockwise"),
    S.ON_HOLD: ("#868e96", "bi-pause-circle"),
    S.CANCELLED: ("#495057", "bi-x-circle"),
    S.CLOSED: ("#146c43", "bi-lock"),
}


class Priority(models.TextChoices):
    LOW = "low", "منخفضة"
    NORMAL = "normal", "عادية"
    IMPORTANT = "important", "مهمة"
    URGENT = "urgent", "عاجلة"
    CRITICAL = "critical", "حرجة"


PRIORITY_STYLE = {
    Priority.LOW: "#8a8f98",
    Priority.NORMAL: "#1c6dd0",
    Priority.IMPORTANT: "#f18927",
    Priority.URGENT: "#dc3545",
    Priority.CRITICAL: "#8b1a1a",
}
PRIORITY_WEIGHT = {Priority.LOW: 1, Priority.NORMAL: 2, Priority.IMPORTANT: 3, Priority.URGENT: 4, Priority.CRITICAL: 5}


class Source(models.TextChoices):
    MEETING_DECISION = "meeting_decision", "قرار اجتماع"
    ED_ASSIGNMENT = "ed_assignment", "تكليف المدير التنفيذي"
    OPERATIONAL_PLAN = "operational_plan", "خطة تشغيلية"
    INCOMING = "incoming_letter", "مراسلة واردة"
    OUTGOING = "outgoing_letter", "مراسلة صادرة"
    INTERNAL = "internal_procedure", "إجراء داخلي"
    PROJECT = "project", "مشروع"
    UNIT_REQUEST = "unit_request", "طلب وحدة"
    STANDALONE = "standalone", "مهمة مستقلة"
    OTHER = "other", "أخرى"


class Confidentiality(models.TextChoices):
    NORMAL = "normal", "عادية"
    CONFIDENTIAL = "confidential", "سرية"
    TOP_SECRET = "top_secret", "سرية للغاية"


class AssigneeRole(models.TextChoices):
    PRIMARY = "primary", "مسؤول رئيسي"
    PARTICIPANT = "participant", "مشارك"


class UnitRole(models.TextChoices):
    LEAD = "lead", "وحدة قائدة"
    PARTICIPANT = "participant", "وحدة مشاركة"


class SubtaskStatus(models.TextChoices):
    NEW = "new", "جديدة"
    IN_PROGRESS = "in_progress", "قيد التنفيذ"
    STALLED = "stalled", "متعثرة"
    COMPLETED = "completed", "مكتملة"
    CANCELLED = "cancelled", "ملغاة"


class ObstacleType(models.TextChoices):
    WAITING_APPROVAL = "waiting_approval", "انتظار اعتماد"
    MISSING_INFO = "missing_info", "نقص معلومات"
    RESOURCES = "resources", "نقص موارد"
    STAFF = "staff", "نقص موظفين"
    FINANCIAL = "financial", "اعتماد مالي"
    ADMIN_APPROVAL = "admin_approval", "اعتماد إداري"
    EXTERNAL = "external", "جهة خارجية"
    TECHNICAL = "technical", "مشكلة تقنية"
    WORKLOAD = "workload", "ضغط أعمال"
    SUPPLIER = "supplier", "تأخر مورد"
    OTHER_UNIT = "other_unit", "تأخر وحدة أخرى"
    OTHER = "other", "أخرى"


class Impact(models.TextChoices):
    LOW = "low", "منخفض"
    MEDIUM = "medium", "متوسط"
    HIGH = "high", "مرتفع"
    CRITICAL = "critical", "حرج"


class ObstacleStatus(models.TextChoices):
    OPEN = "open", "مفتوح"
    RESPONDED = "responded", "تم الرد"
    RESOLVED = "resolved", "تمت المعالجة"


OPEN_OBSTACLE_STATUSES = [ObstacleStatus.OPEN, ObstacleStatus.RESPONDED]


class EscalationTarget(models.TextChoices):
    OWNER = "owner", "المسؤول الرئيسي"
    PARTICIPANTS = "participants", "المشاركون"
    UNIT_HEAD = "unit_head", "رئيس الوحدة"
    ED_ASSISTANT = "ed_assistant", "مساعد المدير التنفيذي"
    EXECUTIVE_DIRECTOR = "executive_director", "المدير التنفيذي"


ESCALATION_LEVEL_LABELS = {0: "—", 1: "رئيس الوحدة", 2: "مساعد المدير التنفيذي", 3: "المدير التنفيذي"}
