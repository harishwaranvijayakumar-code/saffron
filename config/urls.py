from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from config.views import health, readiness
from runs.views import (
    create_run_view,
    dashboard,
    home,
    run_detail,
    confirm_dune_plan_view,
)

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),

    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
        ),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(next_page="login"),
        name="logout",
    ),

    path("runs/", dashboard, name="runs-dashboard"),
    path("runs/new/", create_run_view, name="run-create"),
    path("runs/<uuid:run_id>/", run_detail, name="run-detail"),
    path("runs/confirm-plan/", confirm_dune_plan_view, name="run-confirm-plan"),
    path("ready/", readiness, name="readiness"),
]
