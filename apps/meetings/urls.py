from django.urls import path

from . import views

app_name = "meetings"

urlpatterns = [
    path("", views.decisions_list, name="decisions"),
    path("meetings/", views.meetings_list, name="meetings"),
    path("new/", views.decision_create, name="decision_create"),
    path("tracking/", views.tracking, name="tracking"),
    path("<int:pk>/", views.decision_detail, name="decision_detail"),
    path("<int:pk>/convert/", views.decision_convert, name="convert"),
    path("attachments/<int:pk>/", views.decision_attachment, name="attachment"),
]
