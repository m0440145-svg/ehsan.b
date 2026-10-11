from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("statuses/", views.statuses, name="statuses"),
    path("priorities/", views.priorities, name="priorities"),
    path("task-types/", views.task_types, name="task_types"),
    path("task-types/<int:pk>/", views.task_types, name="task_type_edit"),
    path("rules/", views.rules, name="rules"),
    path("escalation/", views.escalation_rules, name="escalation_rules"),
    path("escalation/<int:pk>/", views.escalation_rules, name="escalation_rule_edit"),
    path("escalation/<int:pk>/toggle/", views.escalation_rule_toggle, name="escalation_rule_toggle"),
    path("notifications/", views.notification_settings, name="notification_settings"),
    path("audit/", views.audit_log, name="audit"),
    path("organization/", views.organization_settings, name="organization"),
    path("getting-started/", views.getting_started, name="getting_started"),
]
