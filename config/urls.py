"""Конфигурация URL проекта supply_service."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.sso_client import views as sso_views

# --- Маршруты ---
urlpatterns = [
    # При едином входе пароль меняется в сервисе авторизации, а не в админке
    path("admin/password_change/", sso_views.password_change),
    path("admin/", admin.site.urls),
    path("reports/", include("core.urls")),
    # Единый вход (работает, только если в .env задан SSO_SERVER_URL)
    path("sso/", include("apps.sso_client.urls")),
    path("", RedirectView.as_view(url="/reports/", permanent=False)),
]
