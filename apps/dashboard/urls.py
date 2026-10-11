from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/me/", views.employee_dashboard, name="employee"),
    path("dashboard/unit/", views.unit_dashboard, name="unit"),
    path("dashboard/executive/", views.executive_dashboard, name="executive"),
    path("dashboard/admin/", views.admin_dashboard, name="admin"),
    path("dashboard/run-engine/", views.run_engine_now, name="run_engine"),
]
