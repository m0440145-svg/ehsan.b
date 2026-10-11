from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("followup/", include("apps.tasks.followup")),
    path("decisions/", include("apps.meetings.urls")),
    path("reports/", include("apps.reports.urls")),
    path("org/", include("apps.organization.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("settings/", include("apps.core.urls")),
    path("api/v1/", include("config.api")),
    path("django-admin/", admin.site.urls),
]

handler403 = "apps.core.errors.forbidden"
handler404 = "apps.core.errors.not_found"
handler500 = "apps.core.errors.server_error"
