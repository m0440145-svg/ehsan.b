from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/verify/", views.otp_view, name="otp"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("users/", views.users_list, name="users"),
    path("users/new/", views.user_form, name="user_create"),
    path("users/<int:pk>/", views.user_form, name="user_edit"),
    path("users/<int:pk>/unlock/", views.user_unlock, name="user_unlock"),
    path("roles/", views.roles_view, name="roles"),
]
