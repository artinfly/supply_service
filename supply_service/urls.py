# Корневая таблица адресов: всё, что начинается с /reports/, уходит в приложение.
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("reports/", include("reports.urls")),
    path("", RedirectView.as_view(url="/reports/", permanent=False)),
]
