"""
Middleware для проверки прав доступа к разделам приложения.

Каждый маршрут имеет имя (url_name), по ключевым словам в котором определяется
раздел. Если у пользователя нет соответствующего права из модели Access,
доступ запрещается с кодом 403.

Проверка происходит на трёх уровнях:
- Страницы (рендер шаблона)
- JSON API (ответ с ошибкой)
- Выгрузки (отдают файл)
"""

from django.http import JsonResponse
from django.shortcuts import render

from .services.queries import YEARS

# Соответствие прав доступа и ключевых слов в имени маршрута.
# Порядок важен: более специфичные разделы проверяются раньше,
# чтобы не было ложных срабатываний.
# Например: "access_export" стоит перед "access_kdr", потому что
# маршрут "export_kdr" должен считаться выгрузкой, а не КДР.
# Аналогично: "znp_sap" раньше "znp", чтобы "znp_sap_list" не попал в "znp".
SECTIONS = (
    # Загрузка файлов (права: access_upload)
    ("access_upload", ("upload",)),
    # Выгрузки Excel (права: access_export)
    ("access_export", ("export",)),
    # Заявки SAP (права: access_znp_sap)
    ("access_znp_sap", ("znp_sap",)),
    # Заявки ФЗД (права: access_znp)
    ("access_znp", ("znp",)),
    # ИГК по годам (права: access_igk)
    ("access_igk", ("igk",)),
    # КДР по годам (права: access_kdr)
    ("access_kdr", ("kdr",)),
    # История изменений (права: access_history)
    ("access_history", ("history",)),
    # Дубликаты (права: access_dupes)
    ("access_dupes", ("dupes",)),
    # Договорная работа: сводки и реестры (права: access_dashboard)
    # Включает: dashboard, all_contracts, chart_contracts
    ("access_dashboard", ("dashboard", "contracts", "chart")),
)


def perm_for(url_name):
    """
    Определяет требуемое право доступа по имени маршрута.

    Ищет первое совпадение ключевого слова в SECTIONS и возвращает
    полное имя права (например: "reports.access_dashboard").

    Возвращает None, если маршрут не требует проверки прав
    (например: главная страница, вход, выход).
    """
    for section, words in SECTIONS:
        if any(word in url_name for word in words):
            return f"reports.{section}"
    return None


class SectionAccessMiddleware:
    """
    Middleware для проверки прав доступа по разделам.

    Вызывается на этапе обработки запроса (процессинг представления).
    Если у пользователя нет нужного права — возвращает 403.

    Суперпользователь проходит все проверки автоматически, потому что
    has_perm() возвращает True для всех прав у суперпользователя.
    """

    def __init__(self, get_response):
        # Стандартная инициализация middleware
        self.get_response = get_response

    def __call__(self, request):
        # Пропускаем запрос дальше по цепочке middleware
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Проверяет права доступа перед вызовом представления.

        Логика:
        1. Если маршрут не имеет имени или в другом пространстве имён — пропускаем
        2. Если маршрут не требует прав или пользователь не аутентифицирован — пропускаем
           (аутентификация проверяется отдельно через @login_required)
        3. Если у пользователя есть право — пропускаем
        4. Иначе — возвращаем 403:
           - Для API: JSON с ошибкой
           - Для страниц: рендер шаблона доступа запрещён
        """
        match = request.resolver_match

        # Пропускаем маршруты без имени или из других приложений
        if match is None or not match.url_name or match.namespace:
            return None

        # Определяем требуемое право по имени маршрута
        perm = perm_for(match.url_name)

        # Если право не требуется или пользователь не аутентифицирован — пропускаем.
        # НЕ аутентифицированных пользователей перехватит @login_required
        # или другие механизмы аутентификации.
        if perm is None or not request.user.is_authenticated:
            return None

        # Проверяем наличие права у пользователя
        if request.user.has_perm(perm):
            return None  # Право есть — разрешаем доступ

        # Права нет — возвращаем 403
        # Для API-запросов возвращаем JSON с ошибкой
        if match.url_name.startswith("api_"):
            return JsonResponse({"error": "нет доступа к разделу"}, status=403)

        # Для страниц рендерим шаблон с сообщением о запрете доступа
        # Передаём years для корректного отображения меню
        return render(request, "access_denied.html", {"years": YEARS}, status=403)
