"""Проверка прав доступа к разделам по имени маршрута.

Каждый маршрут из core/urls.py явно привязан к праву «раздела» (модель Access).
Раньше право угадывалось по подстроке в имени маршрута, и, например,
«sum_report_upload» попадал в «Загрузку данных» из-за слова «upload».

Правила:
  - маршрут в PUBLIC_ROUTES — доступен всем вошедшим пользователям;
  - маршрут в ROUTE_PERMISSIONS — нужен соответствующий access_*;
  - любой другой маршрут core (новый, ещё не внесённый сюда) —
    только суперпользователю. Так новая страница закрыта, пока её явно
    не добавят в таблицу ниже.
Суперпользователь проходит везде (has_perm у него всегда True).
Запросы данных (api_*, AJAX) получают JSON: 401 — если сессия истекла,
403 — если нет права; обычные страницы — вход или страницу «Недостаточно прав».
"""

import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

from .services.queries import YEARS

logger = logging.getLogger(__name__)

# Маршруты без ограничения по разделам (вход обязателен — это проверяет login_required)
PUBLIC_ROUTES = {"root", "login", "logout"}

# Раздел (право access_*) -> маршруты этого раздела
_SECTIONS = {
    "access_dashboard": (
        "dashboard",
        "all_contracts_table",
        "api_all_contracts",
        "api_chart_contracts",
    ),
    "access_znp": (
        "znp_table",
        "znp_list_table",
        "api_znp_list",
        "api_chart_znp",
    ),
    "access_znp_sap": (
        "znp_sap_table",
        "znp_sap_list_table",
        "api_znp_sap_list",
        "api_chart_znp_sap",
    ),
    "access_kdr": ("kdr_table_default", "kdr_table", "api_kdr"),
    "access_igk": (
        "igk_concluded_table_default",
        "igk_concluded_table",
        "igk_not_concluded_table_default",
        "igk_not_concluded_table",
        "igk_terminated_table_default",
        "igk_terminated_table",
        "api_igk_concluded",
        "api_igk_not_concluded",
        "api_igk_terminated",
        "api_igk_detail",
    ),
    "access_history": (
        "history_status_table",
        "history_plan_table",
        "history_fact_table",
        "api_history_status",
        "api_history_plan",
        "api_history_fact",
    ),
    "access_dupes": (
        "contract_dupes_table",
        "api_contract_dupes",
        "api_contract_dupes_by_order",
    ),
    "access_export": (
        "export_page",
        "export_advances",
        "export_kdr",
        "export_contracts_by_agent",
        "export_history_status",
        "export_history_plan",
        "export_history_fact",
        "export_contract_dupes",
        "export_contract_dupes_by_order",
        "export_appeared_concluded",
        "export_appeared_not_concluded",
        # Краткая справка: пункт меню показывается по праву «Отчёты в Excel»,
        # поэтому и страница, и формирование справки — по тому же праву
        "sum_report_page",
        "sum_report_upload",
    ),
    "access_upload": ("upload_excel",),
    "access_goz_report": (
        "goz_report",
        # Загрузка справочника из файла дополнительно требует суперпользователя
        # (декоратор superuser_required во views/goz.py); правка записей — нет
        "upload_gk_directory",
        "gk_directory_save",
        "gk_directory_delete",
    ),
}

# Маршрут -> полное имя права, например "dashboard" -> "core.access_dashboard"
ROUTE_PERMISSIONS = {
    route: f"core.{section}" for section, routes in _SECTIONS.items() for route in routes
}


class SectionAccessMiddleware(MiddlewareMixin):
    """Закрывает разделы правами: 403-страница для HTML и JSON для API/AJAX."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match

        # Админка (namespace "admin") и маршруты без имени сюда не относятся
        if match is None or not match.url_name or match.namespace:
            return None

        url_name = match.url_name
        if url_name in PUBLIC_ROUTES:
            return None

        # Запросы данных (их делает JavaScript страниц) ждут JSON. Если сессия
        # истекла, перенаправление на вход вернуло бы HTML-страницу логина, и
        # таблица показала бы непонятную ошибку — поэтому отвечаем 401 с текстом.
        wants_json = (
            url_name.startswith("api_")
            or url_name == "sum_report_upload"
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )

        # Обычную страницу для анонимного пользователя перенаправит на вход
        # login_required во view
        if not request.user.is_authenticated:
            if wants_json:
                return JsonResponse(
                    {"error": "Сессия истекла — обновите страницу и войдите заново"},
                    status=401,
                )
            return None

        perm = ROUTE_PERMISSIONS.get(url_name)
        if perm is None:
            # Маршрут не внесён в таблицу: пускаем только суперпользователя
            if request.user.is_superuser:
                return None
            logger.warning("Маршрут %s не привязан к разделу в middleware.py", url_name)
        elif request.user.has_perm(perm):
            return None

        if wants_json:
            return JsonResponse({"error": "Нет доступа к разделу"}, status=403)

        return render(request, "access_denied.html", {"years": YEARS}, status=403)
