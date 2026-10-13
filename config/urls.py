"""Конфигурация URL проекта supply_service."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

# --- Маршруты ---
urlpatterns = [
    path("admin/", admin.site.urls),
    path("reports/", include("core.urls")),
    path("", RedirectView.as_view(url="/reports/", permanent=False)),
]
