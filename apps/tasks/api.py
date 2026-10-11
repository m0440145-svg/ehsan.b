"""REST API للمهام: تستخدم نفس طبقة الخدمات ونفس محددات الصلاحيات المستخدمة في الواجهة."""
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.core.permissions import HasPermCode

from . import selectors, services
from .models import Task, TaskObstacle
from .serializers import (
    AttachmentSerializer,
    CommentSerializer,
    ObstacleSerializer,
    ProgressSerializer,
    SubtaskSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
    TaskWriteSerializer,
    UpdateSerializer,
)


class TaskFilter(filters.FilterSet):
    due_from = filters.DateFilter(field_name="due_date", lookup_expr="gte")
    due_to = filters.DateFilter(field_name="due_date", lookup_expr="lte")
    progress_min = filters.NumberFilter(field_name="progress", lookup_expr="gte")
    progress_max = filters.NumberFilter(field_name="progress", lookup_expr="lte")
    employee = filters.NumberFilter(field_name="assignees__employee", distinct=True)
    followup = filters.CharFilter(method="filter_followup")

    class Meta:
        model = Task
        fields = ["status", "priority", "unit", "owner", "source", "confidentiality", "project"]

    def filter_followup(self, qs, name, value):
        return selectors.followup_filter(qs, value)


class TaskViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasPermCode]
    required_perms = {"POST": None}
    filterset_class = TaskFilter
    search_fields = ["number", "title", "description", "owner__full_name", "unit__name", "decisions__number"]
    ordering_fields = ["due_date", "created_at", "progress", "priority", "last_activity_at"]

    def get_queryset(self):
        scope = self.request.query_params.get("scope")
        if scope == "mine":
            return selectors.my_tasks(self.request.user)
        if scope == "unit":
            return selectors.unit_tasks(self.request.user)
        return selectors.visible_tasks(self.request.user)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TaskWriteSerializer
        return TaskDetailSerializer if self.action == "retrieve" else TaskListSerializer

    def create(self, request, *args, **kwargs):
        s = TaskWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        participants = data.pop("participants", [])
        units = data.pop("participant_units", [])
        task = services.create_task(user=request.user, data=data, participants=participants, participant_units=units)
        return Response(TaskDetailSerializer(task).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        task = self.get_object()
        s = TaskWriteSerializer(task, data=request.data, partial=kwargs.get("partial", False))
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        owner = data.pop("owner", None)
        participants = data.pop("participants", None)
        units = data.pop("participant_units", None)
        data.pop("progress", None)
        services.update_task(task, user=request.user, data=data, owner=owner, participants=participants, participant_units=units)
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["post"])
    def progress(self, request, pk=None):
        task = self.get_object()
        s = ProgressSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.update_progress(task, user=request.user, files=request.FILES.getlist("attachments"), **s.validated_data)
        task.refresh_from_db()
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        task = self.get_object()
        if request.method == "POST":
            parent = None
            if request.data.get("parent"):
                parent = get_object_or_404(task.comments, pk=request.data["parent"])
            c = services.add_comment(task, user=request.user, body=request.data.get("body", ""), parent=parent,
                                     files=request.FILES.getlist("attachments"))
            return Response(CommentSerializer(c).data, status=status.HTTP_201_CREATED)
        return Response(CommentSerializer(task.comments.select_related("author"), many=True).data)

    @action(detail=True, methods=["get"])
    def updates(self, request, pk=None):
        return Response(UpdateSerializer(self.get_object().updates.select_related("user"), many=True).data)

    @action(detail=True, methods=["get", "post"])
    def obstacles(self, request, pk=None):
        task = self.get_object()
        if request.method == "POST":
            s = ObstacleSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            ob = services.register_obstacle(task, user=request.user, data=s.validated_data)
            return Response(ObstacleSerializer(ob).data, status=status.HTTP_201_CREATED)
        return Response(ObstacleSerializer(task.obstacles.all(), many=True).data)

    @action(detail=True, methods=["post"], url_path=r"obstacles/(?P<obstacle_id>\d+)/respond")
    def respond_obstacle(self, request, pk=None, obstacle_id=None):
        task = self.get_object()
        ob = get_object_or_404(TaskObstacle, pk=obstacle_id, task=task)
        services.respond_obstacle(ob, user=request.user, response=request.data.get("response", ""),
                                  resolve=str(request.data.get("resolve", "")).lower() in ("1", "true", "yes"))
        return Response(ObstacleSerializer(ob).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        task = services.approve(self.get_object(), user=request.user, notes=request.data.get("notes", ""))
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        task = services.reject(self.get_object(), user=request.user, notes=request.data.get("notes", ""))
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_task(self, request, pk=None):
        task = services.return_task(self.get_object(), user=request.user, notes=request.data.get("notes", ""))
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        task = services.transition(self.get_object(), user=request.user, to=request.data.get("to"), note=request.data.get("note", ""))
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        task = services.escalate(self.get_object(), user=request.user, reason=request.data.get("reason", ""),
                                 level=request.data.get("level"))
        return Response(TaskDetailSerializer(task).data)

    @action(detail=True, methods=["get", "post"])
    def subtasks(self, request, pk=None):
        task = self.get_object()
        if request.method == "POST":
            s = SubtaskSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            d = s.validated_data
            sub = services.add_subtask(task, user=request.user, title=d["title"], assignee=d.get("assignee"),
                                       due_date=d.get("due_date"), comment=d.get("comment", ""))
            return Response(SubtaskSerializer(sub).data, status=status.HTTP_201_CREATED)
        return Response(SubtaskSerializer(task.subtasks.all(), many=True).data)

    @action(detail=True, methods=["get", "post"])
    def attachments(self, request, pk=None):
        task = self.get_object()
        if request.method == "POST":
            if not (selectors.is_involved(request.user, task) or selectors.is_task_manager(request.user, task)):
                return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)
            atts = [services.add_attachment(task, request.user, f) for f in request.FILES.getlist("files")]
            return Response(AttachmentSerializer(atts, many=True).data, status=status.HTTP_201_CREATED)
        return Response(AttachmentSerializer(task.attachments.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        task = self.get_object()
        logs = AuditLog.objects.filter(task=task).select_related("user")
        return Response([{
            "user": a.user.full_name if a.user else "النظام", "action": a.action, "action_label": a.action_label,
            "description": a.description, "old": a.old_values, "new": a.new_values, "at": a.created_at,
        } for a in logs])
