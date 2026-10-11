from django.urls import path

from . import views

app_name = "organization"

urlpatterns = [
    path("units/", views.units_list, name="units"),
    path("units/new/", views.unit_form, name="unit_create"),
    path("units/<int:pk>/", views.unit_detail, name="unit_detail"),
    path("units/<int:pk>/edit/", views.unit_form, name="unit_edit"),
    path("employees/", views.employees_list, name="employees"),
    path("employees/new/", views.employee_form, name="employee_create"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", views.employee_form, name="employee_edit"),
]
