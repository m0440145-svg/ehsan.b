from rest_framework import serializers

from apps.organization.models import Employee, Unit

from .models import Task, TaskAttachment, TaskComment, TaskObstacle, TaskSubtask, TaskUpdate


class EmployeeMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "full_name", "job_title"]


class TaskListSerializer(serializers.ModelSerializer):
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    is_late = serializers.BooleanField(read_only=True)

    class Meta:
        model = Task
        fields = ["id", "number", "title", "unit", "unit_name", "owner", "owner_name", "priority", "priority_display",
                  "status", "status_display", "progress", "start_date", "due_date", "days_remaining", "is_late",
                  "flag_needs_followup", "flag_at_risk", "flag_stale", "escalation_level", "last_activity_at"]


class TaskDetailSerializer(TaskListSerializer):
    participants = EmployeeMiniSerializer(many=True, read_only=True)
    participant_unit_ids = serializers.SerializerMethodField()
    decision_ids = serializers.SerializerMethodField()

    class Meta(TaskListSerializer.Meta):
        fields = TaskListSerializer.Meta.fields + [
            "description", "source", "source_reference", "task_type", "project", "confidentiality",
            "expected_result", "success_indicator", "notes", "requires_approval", "auto_progress",
            "participants", "participant_unit_ids", "decision_ids", "completed_at", "closed_at", "created_at",
        ]

    def get_participant_unit_ids(self, obj):
        return [u.pk for u in obj.participant_units]

    def get_decision_ids(self, obj):
        return list(obj.decisions.values_list("pk", flat=True))


class TaskWriteSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), required=False, allow_null=True)
    participants = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), many=True, required=False)
    participant_units = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), many=True, required=False)
    progress = serializers.IntegerField(required=False, min_value=0, max_value=100)

    class Meta:
        model = Task
        fields = ["title", "description", "source", "source_reference", "task_type", "project", "unit", "owner",
                  "participants", "participant_units", "start_date", "due_date", "priority", "confidentiality",
                  "progress", "expected_result", "success_indicator", "notes", "requires_approval", "auto_progress"]


class ProgressSerializer(serializers.Serializer):
    progress = serializers.IntegerField(min_value=0, max_value=100)
    comment = serializers.CharField()
    done_work = serializers.CharField()
    remaining_work = serializers.CharField(required=False, allow_blank=True)
    update_date = serializers.DateField(required=False)


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)

    class Meta:
        model = TaskComment
        fields = ["id", "parent", "body", "author", "author_name", "created_at"]
        read_only_fields = ["author", "created_at"]


class UpdateSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = TaskUpdate
        fields = ["id", "user_name", "progress_before", "progress_after", "comment", "done_work", "remaining_work",
                  "update_date", "created_at"]


class ObstacleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskObstacle
        fields = ["id", "obstacle_type", "description", "cause_party", "needs_admin_decision", "required_action",
                  "intervener", "expected_resolution_date", "impact", "status", "response", "created_at"]
        read_only_fields = ["status", "response", "created_at"]


class SubtaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSubtask
        fields = ["id", "title", "assignee", "due_date", "status", "progress", "comment"]


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskAttachment
        fields = ["id", "original_name", "size", "kind", "created_at"]
