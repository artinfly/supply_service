"""
Middleware для проверки прав доступа к разделам приложения.

Определяет раздел по ключевым словам в имени маршрута (url_name)
и проверяет наличие соответствующего права из модели Access.
При отсутствии права возвращает 403 (JSON для API, шаблон для страниц).
"""

from django.http import JsonResponse
from django.shortcuts import render

from .services.queries import YEARS

# Соответствие прав доступа и ключевых слов в имени маршрута.
# Порядок важен: более специфичные разделы проверяются раньше,
# чтобы избежать ложных срабатываний.
# Например: "export" перед "kdr", чтобы "export_kdr" считался выгрузкой.
# "znp_sap" раньше "znp", чтобы "znp_sap_list" не попал в "znp".
SECTIONS = (
    ("access_upload", ("upload",)),
    ("access_goz_report", ("goz",)),
    ("access_export", ("export",)),
    ("access_znp_sap", ("znp_sap",)),
    ("access_znp", ("znp",)),
    ("access_igk", ("igk",)),
    ("access_kdr", ("kdr",)),
    ("access_history", ("history",)),
    ("access_dupes", ("dupes",)),
    ("access_dashboard", ("dashboard", "contracts", "chart")),
)


def perm_for(url_name):
    """
    Определяет требуемое право доступа по имени маршрута.
    Возвращает полное имя права (например, "reports.access_dashboard")
    или None, если маршрут не требует проверки прав.
    """
    for section, words in SECTIONS:
        if any(word in url_name for word in words):
            return f"reports.{section}"
    return None


class SectionAccessMiddleware:
    """Middleware для проверки прав доступа по разделам."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Проверяет права доступа перед вызовом представления."""
        match = request.resolver_match

        # Пропускаем маршруты без имени или из других приложений
        if match is None or not match.url_name or match.namespace:
            return None

        perm = perm_for(match.url_name)

        # Пропускаем, если право не требуется или пользователь не аутентифицирован.
        # Неаутентифицированных пользователей перехватит @login_required.
        if perm is None or not request.user.is_authenticated:
            return None

        if request.user.has_perm(perm):
            return None

        # Возвращаем 403: JSON для API, шаблон для страниц
        if match.url_name.startswith("api_"):
            return JsonResponse({"error": "нет доступа к разделу"}, status=403)

        return render(request, "access_denied.html", {"years": YEARS}, status=403)
