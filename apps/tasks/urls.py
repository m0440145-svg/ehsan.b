from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, {"scope": "all"}, name="all"),
    path("mine/", views.task_list, {"scope": "my"}, name="my"),
    path("unit/", views.task_list, {"scope": "unit"}, name="unit"),
    path("new/", views.task_create, name="create"),
    path("search/", views.search, name="search"),
    path("mentions/", views.mention_search, name="mentions"),
    path("<int:pk>/", views.task_detail, name="detail"),
    path("<int:pk>/edit/", views.task_edit, name="edit"),
    path("<int:pk>/progress/", views.action_progress, name="progress"),
    path("<int:pk>/comment/", views.action_comment, name="comment"),
    path("<int:pk>/reply/", views.action_quick_reply, name="quick_reply"),
    path("<int:pk>/upload/", views.action_upload, name="upload"),
    path("<int:pk>/obstacle/", views.action_obstacle, name="obstacle"),
    path("<int:pk>/obstacle/<int:obstacle_id>/respond/", views.action_obstacle_respond, name="obstacle_respond"),
    path("<int:pk>/obstacle/<int:obstacle_id>/resolve/", views.action_obstacle_resolve, name="obstacle_resolve"),
    path("<int:pk>/approve/", views.action_approve, name="approve"),
    path("<int:pk>/reject/", views.action_reject, name="reject"),
    path("<int:pk>/return/", views.action_return, name="return"),
    path("<int:pk>/transition/", views.action_transition, name="transition"),
    path("<int:pk>/escalate/", views.action_escalate, name="escalate"),
    path("<int:pk>/subtasks/", views.action_subtask_add, name="subtask_add"),
    path("<int:pk>/subtasks/<int:sub_id>/", views.action_subtask_update, name="subtask_update"),
    path("attachments/<int:pk>/", views.attachment_download, name="attachment"),
]
