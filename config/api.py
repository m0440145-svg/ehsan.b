"""تجميع واجهات REST API (الإصدار v1) – نقطة التكامل مع الأنظمة الخارجية."""
from datetime import date

from django.contrib.auth import authenticate
from django.urls import include, path
from rest_framework import routers, serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.audit import services as audit
from apps.core.permissions import HasPermCode, has_perm
from apps.meetings import services as meeting_services
from apps.meetings.models import Meeting, MeetingDecision
from apps.notifications.models import Notification
from apps.notifications.services import mark_read
from apps.organization.models import Employee, Unit
from apps.reports.kpis import compute_kpis, group_stats
from apps.reports.registry import REPORTS, build_report
from apps.tasks import selectors
from apps.tasks.api import TaskViewSet
from apps.tasks.serializers import TaskListSerializer


class UnitSerializer(serializers.ModelSerializer):
    head_name = serializers.CharField(source="head.full_name", read_only=True, default=None)

    class Meta:
        model = Unit
        fields = ["id", "name", "code", "description", "head", "head_name", "is_active", "established_on"]


class EmployeeSerializer(serializers.ModelSerializer):
    unit_ids = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ["id", "employee_no", "full_name", "job_title", "manager", "status", "join_date", "unit_ids"]

    def get_unit_ids(self, obj):
        return [u.pk for u in obj.units.all()]


class UnitViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Unit.objects.select_related("head")
    serializer_class = UnitSerializer
    search_fields = ["name", "code"]


class EmployeeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Employee.objects.prefetch_related("units")
    serializer_class = EmployeeSerializer
    filterset_fields = ["status", "units"]
    search_fields = ["full_name", "employee_no", "job_title"]


class MeetingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Meeting
        fields = ["id", "number", "title", "committee", "date", "location", "external_ref", "notes"]


class DecisionSerializer(serializers.ModelSerializer):
    meeting_title = serializers.CharField(source="meeting.title", read_only=True)
    task_ids = serializers.SerializerMethodField()

    class Meta:
        model = MeetingDecision
        fields = ["id", "number", "meeting", "meeting_title", "text", "decision_date", "due_date", "status",
                  "followup_owner", "implementation_pct", "task_ids"]
        read_only_fields = ["status", "implementation_pct"]

    def get_task_ids(self, obj):
        return list(obj.tasks.values_list("pk", flat=True))


class MeetingViewSet(viewsets.ModelViewSet):
    queryset = Meeting.objects.all()
    serializer_class = MeetingSerializer
    permission_classes = [HasPermCode]
    required_perms = {"GET": "decisions.view", "*": "decisions.manage"}
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        m = serializer.save(created_by=self.request.user)
        audit.log("meeting.created", obj=m, description=m.title)


class DecisionViewSet(viewsets.ModelViewSet):
    queryset = MeetingDecision.objects.select_related("meeting")
    serializer_class = DecisionSerializer
    permission_classes = [HasPermCode]
    required_perms = {"GET": "decisions.view", "*": "decisions.manage"}
    filterset_fields = ["meeting", "status"]
    search_fields = ["number", "text", "meeting__title"]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = meeting_services.create_decision(user=request.user, data=s.validated_data)
        return Response(DecisionSerializer(d).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        """items: [{title, unit, owner, participants[], due_date, priority}]"""
        decision = self.get_object()
        units = {u.pk: u for u in Unit.objects.all()}
        emps = {e.pk: e for e in Employee.objects.all()}
        items = []
        for it in request.data.get("items", []):
            items.append({
                "title": it.get("title", ""), "unit": units.get(int(it.get("unit", 0) or 0)),
                "owner": emps.get(int(it.get("owner") or 0)),
                "participants": [emps[int(p)] for p in it.get("participants", []) if int(p) in emps],
                "due_date": date.fromisoformat(it["due_date"]), "priority": it.get("priority", "normal"),
            })
        if any(i["unit"] is None for i in items):
            return Response({"detail": "الوحدة مطلوبة لكل مهمة"}, status=status.HTTP_400_BAD_REQUEST)
        tasks = meeting_services.convert_to_tasks(decision, user=request.user, items=items)
        return Response(TaskListSerializer(tasks, many=True).data, status=status.HTTP_201_CREATED)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "event", "title", "body", "task", "url", "is_read", "created_at"]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    filterset_fields = ["is_read", "event"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=False, methods=["post"])
    def mark_read(self, request):
        ids = request.data.get("ids")
        return Response({"updated": mark_read(request.user, ids)})


@api_view(["GET"])
def dashboard_kpis(request):
    qs = selectors.visible_tasks(request.user)
    data = {"kpis": compute_kpis(qs)}
    if has_perm(request.user, "dashboard.executive") or has_perm(request.user, "dashboard.unit"):
        data["units"] = group_stats(qs, "unit")
    return Response(data)


@api_view(["GET"])
def report_api(request, key):
    if not has_perm(request.user, "reports.view") or key not in REPORTS:
        return Response({"detail": "غير متاح"}, status=status.HTTP_404_NOT_FOUND)
    filters = {k: v for k, v in request.query_params.items() if v}
    r = build_report(key, selectors.visible_tasks(request.user), filters)
    return Response({k: r[k] for k in ("key", "title", "columns", "rows", "kpis")})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def obtain_token(request):
    """إصدار Token للتكامل مع الأنظمة الخارجية (محدود المعدل)."""
    user = authenticate(request, username=request.data.get("identifier"), password=request.data.get("password"))
    if not user:
        return Response({"detail": "بيانات الدخول غير صحيحة"}, status=status.HTTP_400_BAD_REQUEST)
    token, _ = Token.objects.get_or_create(user=user)
    audit.log("auth.login", user=user, obj=user, description="إصدار Token لواجهة API")
    return Response({"token": token.key, "user": user.full_name, "role": user.role_code})


obtain_token.cls.throttle_scope = "auth"

router = routers.DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("units", UnitViewSet)
router.register("employees", EmployeeViewSet)
router.register("meetings", MeetingViewSet)
router.register("decisions", DecisionViewSet)
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path("auth/token/", obtain_token, name="api-token"),
    path("dashboard/kpis/", dashboard_kpis, name="api-kpis"),
    path("reports/<slug:key>/", report_api, name="api-report"),
    path("", include(router.urls)),
]
