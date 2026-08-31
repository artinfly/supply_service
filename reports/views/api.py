"""
JSON API для таблиц и графиков.

Страницы отдают только каркас, данные подгружаются запросами к этим эндпоинтам.
Все данные берутся через сырой SQL из services/queries.py и services/charts.py.

Формат ответа: список объектов (для таблиц) или структура для Chart.js (для графиков).
"""

from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Q
from django.http import JsonResponse

from ..models import ZnpDataSAP
from ..services.charts import (
    CONTRACT_AGE,
    SAP_STAGES,
    ZNP_STAGES,
    contracts_by_cfo,
    znp_by_cfo,
    znp_sap_by_cfo,
)
from ..services.queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    POSTPAYMENT,
    SAP_CFO,
    TERMINATED,
    YEAR_COL,
    ZNP_APPROVED,
    all_contracts,
    contract_dupes,
    contract_dupes_by_order,
    escape_like,
    history_fact,
    history_plan,
    history_status,
    igk_detail,
    igk_stat,
    igk_stat_total,
    kdr,
    needs_znp,
    valid_date,
    valid_year,
    znp_list,
)
from ..services.sap_status import (
    SAP_STAGE_LABELS,
    sap_status_conditions,
    sap_status_expr,
)

# ============================================================================
# Вспомогательные функции для JSON-ответов
# ============================================================================


def _to_json_types(rows):
    """
    Конвертирует Decimal в int/float для сериализации в JSON.

    Целые Decimal превращаются в int (например: 100.00 -> 100),
    дробные — в float (например: 100.50 -> 100.5).
    """
    for row in rows:
        for k, v in row.items():
            if isinstance(v, Decimal):
                row[k] = int(v) if v == v.to_integral_value() else float(v)
    return rows


def _json_rows(cur):
    """Преобразует результат курсора в список словарей с типами для JSON."""
    cols = [c[0] for c in cur.description]
    return _to_json_types([dict(zip(cols, r)) for r in cur.fetchall()])


def _json_response(sql, params=None):
    """
    Универсальный JSON-ответ: выполняет SQL и возвращает список строк.

    Используется для реестров с простой структурой.
    """
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return JsonResponse(
            _json_rows(cur), safe=False, json_dumps_params={"ensure_ascii": False}
        )


def _igk_response(year, statuses):
    """
    Ответ для страниц ИГК по годам: строки по ИГК + итоговая строка.

    Сначала запрашивает детальные строки (по каждому ИГК), затем добавляет
    итоговую строку с агрегатами по всем ИГК.
    """
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        # Детальные строки по каждому ИГК
        cur.execute(igk_stat(yc, statuses))
        rows = _json_rows(cur)
        # Итоговая строка (агрегаты по всем ИГК)
        cur.execute(igk_stat_total(yc, statuses))
        rows.append(dict(zip([c[0] for c in cur.description], cur.fetchone())))
    return JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})


# ============================================================================
# Реестры по годам: КДР и ИГК
# ============================================================================


@login_required
def api_kdr(request, year):
    """Данные для таблицы «Контроль договорной работы» за год."""
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    return _json_response(kdr(year))


@login_required
def api_igk_concluded(request, year):
    """Данные для таблицы «Заключённые по ИГК» за год."""
    return _igk_response(year, CONCLUDED)


@login_required
def api_igk_not_concluded(request, year):
    """Данные для таблицы «Незаключённые по ИГК» за год."""
    return _igk_response(year, NOT_CONCL)


@login_required
def api_igk_terminated(request, year):
    """Данные для таблицы «Расторгнутые по ИГК» за год."""
    return _igk_response(year, TERMINATED)


# ============================================================================
# История изменений
# ============================================================================


@login_required
def api_history_status(request):
    """Данные для таблицы «История изменений статуса»."""
    return _json_response(history_status())


@login_required
def api_history_plan(request):
    """Данные для таблицы «История изменений плана»."""
    return _json_response(history_plan())


@login_required
def api_history_fact(request):
    """Данные для таблицы «История изменений факта»."""
    return _json_response(history_fact())


# ============================================================================
# Дубликаты договоров
# ============================================================================


@login_required
def api_contract_dupes(request):
    """Данные для таблицы «Дубликаты договоров» (полные повторы строк)."""
    sql, params = contract_dupes(
        request.GET.get("cfo", "").strip(),
        request.GET.get("year", "").strip(),
    )
    return _json_response(sql, params)


@login_required
def api_contract_dupes_by_order(request):
    """Данные для таблицы «Дубликаты по заказу» (по ИГК, предмету, заказу)."""
    sql, params = contract_dupes_by_order(
        request.GET.get("cfo", "").strip(),
        request.GET.get("year", "").strip(),
    )
    return _json_response(sql, params)


# ============================================================================
# Детализация по ИГК
# ============================================================================


@login_required
def api_igk_detail(request, year, igk):
    """
    Детальная страница по одному ИГК за год.

    Открывается при раскрытии строки в реестрах ИГК.
    Показывает позиции договоров, входящих в этот ИГК.

    Параметры:
    - type: concluded | not_concluded | terminated (по умолчанию: concluded)
    """
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    report_type = request.GET.get("type", "concluded")
    statuses = {"concluded": CONCLUDED, "not_concluded": NOT_CONCL}.get(
        report_type, TERMINATED
    )
    return _json_response(igk_detail(year, igk, statuses), [f"%{escape_like(igk)}"])


# ============================================================================
# Реестр всех договоров
# ============================================================================


@login_required
def api_all_contracts(request):
    """
    Реестр всех договоров с фильтрами.

    Фильтры (все необязательные):
    - agent: поиск по контрагенту или номеру договора
    - igk: фильтр по ИГК
    - cfo: фильтр по ЦФО
    - status: список статусов (может быть несколько)
    - year: фильтр по году

    Возвращает строки, сгруппированные по (ИГК, договор, заказ),
    после каждой группы добавляется итоговая строка.
    """
    # Читаем параметры фильтров
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]
    year_filter = request.GET.get("year", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()

    # Базовое условие: только строки с типом платежа (валидные строки)
    conditions = ["payment_type IS NOT NULL AND TRIM(payment_type) != ''"]
    params = []

    # Фильтр по контрагенту или номеру договора
    if agent:
        conditions.append("(c_agent ILIKE %s OR contract ILIKE %s)")
        params.append(f"%{escape_like(agent)}%")
        params.append(f"%{escape_like(agent)}%")

    # Фильтр по ИГК
    if igk_filter:
        conditions.append("igk LIKE %s")
        params.append(f"%{escape_like(igk_filter)}")

    # Фильтр по ЦФО
    if cfo_filter:
        conditions.append("cfo LIKE %s")
        params.append(f"%{escape_like(cfo_filter)}")

    # Фильтр по статусам: если статусы заданы, но ни один не валиден — FALSE
    if statuses:
        conditions.append(f"status IN ({','.join(['%s'] * len(statuses))})")
        params.extend(statuses)
    elif raw_statuses:
        conditions.append("FALSE")

    # Фильтр по году: колонка-флаг должна быть TRUE
    if year_filter in YEAR_COL:
        conditions.append(f"{YEAR_COL[year_filter]} = TRUE")

    where = "WHERE " + " AND ".join(conditions)
    detail_sql, total_sql = all_contracts(where)

    with connection.cursor() as cur:
        # Детальные строки
        cur.execute(detail_sql, params)
        cols = [c[0] for c in cur.description]
        detail = [dict(zip(cols, r)) for r in cur.fetchall()]
        # Итоговые строки по группам (ИГК, договор, заказ)
        cur.execute(total_sql, params)
        totals = {(r[0], r[2], r[6]): dict(zip(cols, r)) for r in cur.fetchall()}

    # Группируем строки по (ИГК, договор, заказ) и добавляем итог после каждой группы
    groups = defaultdict(list)
    for row in detail:
        groups[(row["igk"], row["contract"], row["order"])].append(row)

    result = []
    for key, rows in groups.items():
        result.extend(rows)
        if key in totals:
            result.append(totals[key])

    return JsonResponse(
        _to_json_types(result), safe=False, json_dumps_params={"ensure_ascii": False}
    )


# ============================================================================
# Реестр заявок ФЗД
# ============================================================================


# Условия фильтров по статусам заявок ФЗД.
# Ключ — значение параметра "status" из запроса, значение — условие для SQL.
# Используется в api_znp_list.
#
# ВАЖНО: при изменении статусов нужно синхронизировать:
# - здесь (для реестра)
# - в services/dashboards.py (для сводки)
ZNP_STATUS_CONDITIONS = {
    # Не выдана ЗНП: позиции без заявок, где остаток превышает допуск
    "not_issued": f"(z.id IS NULL AND {needs_znp()})",
    # В работе: заявки есть, но не утверждены
    "in_progress": f"(z.id IS NOT NULL AND z.znp_status IS DISTINCT FROM '{ZNP_APPROVED}')",
    # Не выдана ЗНП (аванс)
    "not_issued_advance": (
        f"(z.id IS NULL AND i.payment_type = '{ADVANCE}'" f" AND {needs_znp()})"
    ),
    # Не выдана ЗНП (постоплата)
    "not_issued_postpayment": (
        f"(z.id IS NULL AND i.payment_type = '{POSTPAYMENT}'" f" AND {needs_znp()})"
    ),
    # ЗНП выдана (аванс)
    "advance": (
        f"(z.id IS NOT NULL AND i.payment_type = '{ADVANCE}'"
        f" AND z.znp_status = '{ZNP_APPROVED}')"
    ),
    # Аванс оплачен
    "advance_paid": (
        f"(z.id IS NOT NULL AND i.payment_type = '{ADVANCE}'"
        f" AND z.znp_status = '{ZNP_APPROVED}' AND z.fact_sum IS NOT NULL)"
    ),
    # ЗНП выдана (постоплата)
    "postpayment": (
        f"(z.id IS NOT NULL AND i.payment_type = '{POSTPAYMENT}'"
        f" AND z.znp_status = '{ZNP_APPROVED}')"
    ),
    # Постоплата оплачена
    "postpayment_paid": (
        f"(z.id IS NOT NULL AND i.payment_type = '{POSTPAYMENT}'"
        f" AND z.znp_status = '{ZNP_APPROVED}' AND z.fact_sum IS NOT NULL)"
    ),
}


@login_required
def api_znp_list(request):
    """
    Реестр заявок ФЗД с фильтрами.

    Показывает позиции договоров и привязанные к ним заявки.
    Фильтры:
    - agent: поиск по контрагенту или номеру договора
    - igk: фильтр по ИГК
    - cfo: фильтр по ЦФО
    - year: фильтр по году
    - status: статусы заявок (несколько значений из ZNP_STATUS_CONDITIONS)

    Базовое условие: только заключённые позиции договоров.
    """
    # Читаем параметры фильтров
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    year_filter = request.GET.get("year", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]

    # Базовое условие: только заключённые позиции договоров
    conditions = [f"i.status IN ({','.join(['%s'] * len(CONCLUDED))})"]
    params = list(CONCLUDED)

    # Фильтр по контрагенту или номеру договора
    if agent:
        conditions.append("(i.c_agent ILIKE %s OR i.contract ILIKE %s)")
        params.append(f"%{escape_like(agent)}%")
        params.append(f"%{escape_like(agent)}%")

    # Фильтр по ИГК
    if igk_filter:
        conditions.append("i.igk LIKE %s")
        params.append(f"%{escape_like(igk_filter)}")

    # Фильтр по ЦФО
    if cfo_filter:
        conditions.append("i.cfo LIKE %s")
        params.append(f"%{escape_like(cfo_filter)}")

    # Фильтр по году: колонка-флаг должна быть TRUE
    if year_filter in YEAR_COL:
        conditions.append(f"i.{YEAR_COL[year_filter]} = TRUE")

    # Фильтр по статусам заявок: объединяем условия через OR
    status_conditions = [
        ZNP_STATUS_CONDITIONS[s] for s in statuses if s in ZNP_STATUS_CONDITIONS
    ]
    if status_conditions:
        conditions.append("(" + " OR ".join(status_conditions) + ")")
    elif raw_statuses:
        # Статусы заданы, но ни один не валиден — ничего не показываем
        conditions.append("FALSE")

    where = "WHERE " + " AND ".join(conditions)
    return _json_response(znp_list(where), params)


# ============================================================================
# Реестр заявок SAP
# ============================================================================


@login_required
def api_znp_sap_list(request):
    """
    Реестр заявок SAP с фильтрами.

    В отличие от заявок ФЗД, данные берутся через ORM, а не сырой SQL,
    потому что статус заявки вычисляется по датам этапов (см. sap_status.py).

    Фильтры:
    - agent: поиск по контрагенту или номеру заявки
    - igk: фильтр по ИГК
    - cfo: фильтр по ЦФО
    - status: статусы заявок (ключи из sap_status_conditions)

    Базовое условие: только заявки по ЦФО из списка SAP_CFO.
    """
    # Читаем параметры фильтров
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]

    # Базовое условие: только заявки по ЦФО из списка
    qs = ZnpDataSAP.objects.filter(cfo__in=SAP_CFO)

    # Фильтр по контрагенту или номеру заявки
    if agent:
        qs = qs.filter(Q(c_agent__icontains=agent) | Q(reg_num__icontains=agent))

    # Фильтр по ИГК
    if igk_filter:
        qs = qs.filter(igk__icontains=igk_filter)

    # Фильтр по ЦФО
    if cfo_filter:
        qs = qs.filter(cfo__icontains=cfo_filter)

    # Фильтр по статусам: объединяем через OR
    conditions = sap_status_conditions()
    status_q = Q()
    for s in statuses:
        if s in conditions:
            status_q |= conditions[s]
    if status_q:
        qs = qs.filter(status_q)
    elif raw_statuses:
        # Статусы заданы, но ни один не валиден — ничего не показываем
        qs = qs.none()

    # Аннотируем статус и выбираем поля для ответа
    data = list(
        qs.annotate(status_key=sap_status_expr())
        .order_by("cfo", "reg_num")
        .values(
            "id",
            "igk",
            "cfo",
            "c_agent",
            "reg_num",
            "items",
            "vv_sum",
            "bank_name",
            "stage_e",
            "stage_f",
            "payment_possible",
            "normalize_doc_num",
            "status_key",
        )
    )
    # Заменяем ключ статуса на человекочитаемую подпись,
    # и обрезаем ИГК до последних 4 символов
    for row in data:
        row["sap_status"] = SAP_STAGE_LABELS[row.pop("status_key")]
        if row.get("igk"):
            row["igk"] = str(row["igk"])[-4:]
    return JsonResponse(data, safe=False, json_dumps_params={"ensure_ascii": False})


# ============================================================================
# Графики для сводок
# ============================================================================


def _chart_response(labels, datasets, extra=None):
    """
    Формирует ответ для Chart.js.

    Структура:
    - labels: подписи оси (например, названия ЦФО)
    - datasets: данные для каждой серии
    - extra: дополнительные параметры (заголовок, тип графика и т.д.)
    """
    payload = {"labels": labels, "datasets": datasets}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


def _stacked_by_cfo(sql, params, stages, title):
    """
    Универсальный сборщик стековых графиков по ЦФО.

    Строит график, где ось X — ЦФО (отсортированы по убыванию суммы),
    а каждый сегмент стека — стадия/этап.

    Параметры:
    - sql, params: запрос, возвращающий (ЦФО, стадия, количество, сумма)
    - stages: список (ключ, подпись) для стадий
    - title: заголовок графика

    Возвращает данные в формате для Chart.js.
    """
    with connection.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    # Разделяем данные по стадиям
    totals = {}
    values = {key: {} for key, _ in stages}  # суммы по стадиям и ЦФО
    counts = {key: {} for key, _ in stages}  # количество по стадиям и ЦФО
    for cfo, stage, cnt, amount in rows:
        if stage not in values:
            continue
        # Суммы переводим в миллионы рублей
        mln = float(amount or 0) / 1000000
        values[stage][cfo] = mln
        counts[stage][cfo] = int(cnt or 0)
        totals[cfo] = totals.get(cfo, 0) + mln

    # Сортируем ЦФО по убыванию общей суммы
    labels = sorted(totals, key=lambda cfo: totals[cfo], reverse=True)

    # Собираем данные для каждой стадии
    datasets = [
        {
            "label": label,
            "data": [values[key].get(cfo, 0.0) for cfo in labels],
            "counts": [counts[key].get(cfo, 0) for cfo in labels],
        }
        for key, label in stages
    ]
    return _chart_response(
        labels,
        datasets,
        {
            "unit": "млн ₽",
            "ordinal": True,  # Категориальная ось
            "horizontal": True,  # Горизонтальные столбцы
            "stacked": True,  # Стековый график
            "title": title,
        },
    )


@login_required
def api_chart_contracts(request):
    """
    График «Незаключённые по ЦФО и давности срока» для dashboard.

    Показывает незаключённые договоры выбранного года и ИГК,
    разбитые по ЦФО и давности просрочки.
    """
    year = valid_year(request.GET.get("year"))
    igk = request.GET.get("igk", "").strip()
    if not igk:
        return _chart_response([], [])
    sql, params = contracts_by_cfo(YEAR_COL[str(year)], igk)
    return _stacked_by_cfo(
        sql,
        params,
        CONTRACT_AGE,
        f"Незаключённые по ЦФО и давности срока, ГодИГК {year}",
    )


@login_required
def api_chart_znp(request):
    """
    График «Заявки по ЦФО и стадиям» для сводки заявок ФЗД.

    Показывает заявки выбранного года и ИГК, разбитые по ЦФО и стадиям.
    Необязательный период (start, end) фильтрует заявки по дате.
    """
    year = valid_year(request.GET.get("year"))
    igk = request.GET.get("igk", "").strip()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
    # Если период задан, обе даты должны быть валидными
    if (start or end) and not (valid_date(start) and valid_date(end)):
        return JsonResponse({"error": "недопустимая дата периода"}, status=400)
    if not igk:
        return _chart_response([], [])
    sql, params = znp_by_cfo(YEAR_COL[str(year)], igk, start, end)
    title = f"Заявки по ЦФО и стадиям, ГодИГК {year}"
    if start and end:
        title += f", заявки с {start} по {end}"
    return _stacked_by_cfo(sql, params, ZNP_STAGES, title)


@login_required
def api_chart_znp_sap(request):
    """
    График «Заявки SAP по ЦФО и этапам» для сводки заявок SAP.

    Показывает заявки выбранного ИГК, разбитые по ЦФО и этапам.
    """
    igk = request.GET.get("igk", "").strip()
    sql, params = znp_sap_by_cfo(igk)
    return _stacked_by_cfo(sql, params, SAP_STAGES, "Заявки SAP по ЦФО и этапам")
