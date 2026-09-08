"""
Списки маршрутов для тестов доступа.

Используется в `test_access.py` для проверки прав доступа:
- `RouteMapTests` сверяет этот список с реальным `urls.py`
- `SectionAccessTests` обходит все маршруты и проверяет права

Если добавить новый маршрут в `urls.py`, его нужно добавить сюда,
иначе тест `список_маршрутов_в_тестах_совпадает_с_urls` упадёт.
"""

# Год для маршрутов, требующих параметр `<str:year>`
YEAR = "2026"

# Пример ИГК для маршрута детализации `api_igk_detail`
IGK = "2426187301032442228107"


# Страницы приложения (рендерят шаблоны)
PAGES = [
    ("root", []),
    ("dashboard", []),
    ("kdr_table", [YEAR]),
    ("igk_concluded_table", [YEAR]),
    ("igk_not_concluded_table", [YEAR]),
    ("igk_terminated_table", [YEAR]),
    ("all_contracts_table", []),
    ("znp_table", []),
    ("znp_list_table", []),
    ("znp_sap_table", []),
    ("znp_sap_list_table", []),
    ("history_status_table", []),
    ("history_plan_table", []),
    ("history_fact_table", []),
    ("contract_dupes_table", []),
    ("upload_excel", []),
    ("export_page", []),
]


# Выгрузки Excel (отдают .xlsx файл)
EXPORTS = [
    ("export_advances", [YEAR]),
    ("export_kdr", [YEAR]),
    ("export_contracts_by_agent", [YEAR]),
    ("export_history_status", []),
    ("export_history_plan", []),
    ("export_history_fact", []),
    ("export_contract_dupes", []),
    ("export_contract_dupes_by_order", []),
    ("export_appeared_concluded", []),
    ("export_appeared_not_concluded", []),
]


# JSON API (отдают данные для таблиц и графиков)
APIS = [
    ("api_kdr", [YEAR]),
    ("api_igk_concluded", [YEAR]),
    ("api_igk_not_concluded", [YEAR]),
    ("api_igk_terminated", [YEAR]),
    ("api_all_contracts", []),
    ("api_znp_list", []),
    ("api_znp_sap_list", []),
    ("api_history_status", []),
    ("api_history_plan", []),
    ("api_history_fact", []),
    ("api_contract_dupes", []),
    ("api_contract_dupes_by_order", []),
    ("api_igk_detail", [YEAR, IGK]),
    ("api_chart_contracts", []),
    ("api_chart_znp", []),
    ("api_chart_znp_sap", []),
]


# Объединение всех маршрутов: используется в тестах для обхода
# каждой страницы, выгрузки и API
ALL = PAGES + EXPORTS + APIS
