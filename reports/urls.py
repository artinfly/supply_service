"""
Маршруты приложения reports.

Все URL начинаются с префикса /reports/
Сгруппированы по типу: страницы, выгрузки Excel, JSON-API для таблиц, API графиков.
"""

from django.urls import path

from .views import api, exports, pages

urlpatterns = [
    # ========================================================================
    # Аутентификация и служебные страницы
    # ========================================================================
    # Главная страница приложения
    path("", pages.index, name="root"),
    # Вход в систему
    path("login/", pages.login_view, name="login"),
    # Выход из системы
    path("logout/", pages.logout_view, name="logout"),
    # ========================================================================
    # Сводки и dashboard (страницы с плашками и графиками)
    # ========================================================================
    # Dashboard: общая сводка по договорам с плашками по ЦФО
    path("dashboard/", pages.dashboard, name="dashboard"),
    # Сводка заявок ФЗД с графиком по датам заявок
    path("znp/", pages.znp_table, name="znp_table"),
    # Сводка заявок SAP
    path("znp-sap/", pages.znp_sap_table, name="znp_sap_table"),
    # ========================================================================
    # Реестры: полные списки договоров и заявок с фильтрами
    # ========================================================================
    # Реестр всех договоров
    path("all-contracts/", pages.all_contracts_table, name="all_contracts_table"),
    # Реестр заявок ФЗД
    path("znp-list/", pages.znp_list_table, name="znp_list_table"),
    # Реестр заявок SAP
    path("znp-sap-list/", pages.znp_sap_list_table, name="znp_sap_list_table"),
    # Дубликаты договоров (по ИГК, предмету, заказу и полные повторы строк)
    path("contract-dupes/", pages.contract_dupes_table, name="contract_dupes_table"),
    # ========================================================================
    # Страницы по годам: КДР и ИГК с разбивкой по статусам
    # ========================================================================
    # Контроль договорной работы за конкретный год
    path("kdr/<str:year>/", pages.kdr_table, name="kdr_table"),
    # Заключённые договоры по ИГК за год
    path(
        "igk-concluded/<str:year>/",
        pages.igk_concluded_table,
        name="igk_concluded_table",
    ),
    # Незаключённые договоры по ИГК за год
    path(
        "igk-not-concluded/<str:year>/",
        pages.igk_not_concluded_table,
        name="igk_not_concluded_table",
    ),
    # Расторгнутые договоры по ИГК за год
    path(
        "igk-terminated/<str:year>/",
        pages.igk_terminated_table,
        name="igk_terminated_table",
    ),
    # ========================================================================
    # История изменений договоров (статус, план, факт)
    # ========================================================================
    # История изменений статуса договора
    path("history-status/", pages.history_status_table, name="history_status_table"),
    # История изменений плана
    path("history-plan/", pages.history_plan_table, name="history_plan_table"),
    # История изменений факта
    path("history-fact/", pages.history_fact_table, name="history_fact_table"),
    # ========================================================================
    # Загрузка данных и страница выбора выгрузок
    # ========================================================================
    # Страница загрузки Excel-файлов (договоры, заявки ФЗД, заявки SAP)
    path("upload/", pages.upload_excel, name="upload_excel"),
    # Страница со списком доступных Excel-выгрузок
    path("export/", pages.export_page, name="export_page"),
    # ========================================================================
    # Выгрузки Excel (скачивание готовых .xlsx файлов)
    # ========================================================================
    # Авансы по году (выгрузка по шаблону)
    path(
        "export/advances/<str:year>/", exports.export_advances, name="export_advances"
    ),
    # Контроль договорной работы за год
    path("export/kdr/<str:year>/", exports.export_kdr, name="export_kdr"),
    # Договоры по контрагенту за год
    path(
        "export/contracts/<str:year>/",
        exports.export_contracts_by_agent,
        name="export_contracts_by_agent",
    ),
    # История изменений статуса
    path(
        "export/history-status/",
        exports.export_history_status,
        name="export_history_status",
    ),
    # История изменений плана
    path(
        "export/history-plan/", exports.export_history_plan, name="export_history_plan"
    ),
    # История изменений факта
    path(
        "export/history-fact/", exports.export_history_fact, name="export_history_fact"
    ),
    # Дубликаты договоров (полные повторы строк)
    path(
        "export/contract-dupes/",
        exports.export_contract_dupes,
        name="export_contract_dupes",
    ),
    # Дубликаты договоров по заказу (по ИГК, предмету, заказу)
    path(
        "export/contract-dupes-by-order/",
        exports.export_contract_dupes_by_order,
        name="export_contract_dupes_by_order",
    ),
    # Появившиеся заключённые договоры
    path(
        "export/appeared-concluded/",
        exports.export_appeared_concluded,
        name="export_appeared_concluded",
    ),
    # Появившиеся незаключённые договоры
    path(
        "export/appeared-not-concluded/",
        exports.export_appeared_not_concluded,
        name="export_appeared_not_concluded",
    ),
    # ========================================================================
    # JSON API: данные для таблиц (вызываются AJAX-ом со страниц)
    # ========================================================================
    # Данные для реестра КДР за год
    path("api/kdr/<str:year>/", api.api_kdr, name="api_kdr"),
    # Данные для реестра заключённых договоров по ИГК
    path(
        "api/igk-concluded/<str:year>/", api.api_igk_concluded, name="api_igk_concluded"
    ),
    # Данные для реестра незаключённых договоров по ИГК
    path(
        "api/igk-not-concluded/<str:year>/",
        api.api_igk_not_concluded,
        name="api_igk_not_concluded",
    ),
    # Данные для реестра расторгнутых договоров по ИГК
    path(
        "api/igk-terminated/<str:year>/",
        api.api_igk_terminated,
        name="api_igk_terminated",
    ),
    # Данные для реестра всех договоров
    path("api/all-contracts/", api.api_all_contracts, name="api_all_contracts"),
    # Данные для реестра заявок ФЗД
    path("api/znp/", api.api_znp_list, name="api_znp_list"),
    # Данные для реестра заявок SAP
    path("api/znp-sap/", api.api_znp_sap_list, name="api_znp_sap_list"),
    # Данные для истории изменений статуса
    path("api/history-status/", api.api_history_status, name="api_history_status"),
    # Данные для истории изменений плана
    path("api/history-plan/", api.api_history_plan, name="api_history_plan"),
    # Данные для истории изменений факта
    path("api/history-fact/", api.api_history_fact, name="api_history_fact"),
    # Данные для таблицы дубликатов (полные повторы строк)
    path("api/contract-dupes/", api.api_contract_dupes, name="api_contract_dupes"),
    # Данные для таблицы дубликатов по заказу
    path(
        "api/contract-dupes-by-order/",
        api.api_contract_dupes_by_order,
        name="api_contract_dupes_by_order",
    ),
    # Детальная страница по одному ИГК за год (раскрытие строки в реестре)
    path(
        "api/igk-detail/<str:year>/<str:igk>/",
        api.api_igk_detail,
        name="api_igk_detail",
    ),
    # ========================================================================
    # JSON API: данные для графиков (Chart.js)
    # ========================================================================
    # График по договорам на dashboard
    path("api/chart/contracts/", api.api_chart_contracts, name="api_chart_contracts"),
    # График по заявкам ФЗД
    path("api/chart/znp/", api.api_chart_znp, name="api_chart_znp"),
    # График по заявкам SAP
    path("api/chart/znp-sap/", api.api_chart_znp_sap, name="api_chart_znp_sap"),
]
