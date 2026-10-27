"""JSON API для таблиц и графиков.

Страницы отдают только каркас, а строки таблиц и данные графиков JavaScript
получает отсюда. Все ответы — списки/словари JSON; Decimal приводится к числам.
Фильтры приходят в GET-параметрах; значения пользователя попадают в SQL
только через параметры (%s), в текст запроса — только константы.
"""

from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Q
from django.http import JsonResponse

from ..models import ZnpDataSAP
from ..services.dashboards.charts import (
    CONTRACT_AGE,
    SAP_STAGES,
    ZNP_STAGES,
    contracts_by_cfo,
    znp_by_cfo,
    znp_sap_by_cfo,
)
from ..services.dashboards.sap_status import (
    SAP_STAGE_LABELS,
    sap_date_field,
    sap_status_conditions,
    sap_status_expr,
)
from ..services.queries import (
    ADVANCE,
    ALL_CONTRACTS_GROUP,
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
    dict_rows,
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

# --- Вспомогательные функции для JSON ---


def _to_json_types(rows):
    """Конвертирует Decimal в int/float для JSON-сериализации."""
    for row in rows:
        for k, v in row.items():
            if isinstance(v, Decimal):
                row[k] = int(v) if v == v.to_integral_value() else float(v)
    return rows


def _json_rows(cur):
    """Преобразует результат курсора в список словарей."""
    return _to_json_types(dict_rows(cur))


def _json_response(sql, params=None):
    """Выполняет SQL-запрос и возвращает JSON-ответ."""
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return JsonResponse(
            _json_rows(cur), safe=False, json_dumps_params={"ensure_ascii": False}
        )


def _igk_response(year, statuses):
    """Возвращает статистику по ИГК с итоговой строкой."""
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        cur.execute(igk_stat(yc, statuses))
        rows = _json_rows(cur)
        cur.execute(igk_stat_total(yc, statuses))
        rows += _json_rows(cur)
    return JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})


def _get_filters(request):
    """Извлекает параметры фильтрации из GET-запроса."""
    return {
        "agent": request.GET.get("agent", "").strip(),
        "igk": request.GET.get("igk", "").strip(),
        "cfo": request.GET.get("cfo", "").strip(),
        "year": request.GET.get("year", "").strip(),
        "statuses": [s for s in request.GET.getlist("status") if s],
        "raw_statuses": request.GET.getlist("status"),
    }


# --- API: КДР и ИГК ---


# Проценты строки «ИТОГО» КДР: поле -> (числитель, знаменатель)
_KDR_TOTAL_PERCENTS = {
    "count_concluded_percent_curr_year": (
        "count_concluded_curr_year",
        "count_curr_year",
    ),
    "order_sum_percent_curr_year": (
        "concluded_order_sum_curr_year",
        "order_sum_curr_year",
    ),
    "pp_percent": ("pp_sum_fact", "pp_sum_plan"),
}


def _kdr_total_row(rows):
    """Строка «ИТОГО» для КДР: суммы колонок и проценты, пересчитанные от сумм.

    Проценты нельзя складывать, поэтому они считаются заново из итоговых чисел
    (округление до целого — как в SQL-запросе kdr()).
    """
    total = {"igk": "ИТОГО"}
    for key in rows[0]:
        if key != "igk" and key not in _KDR_TOTAL_PERCENTS:
            total[key] = round(sum(r[key] or 0 for r in rows), 2)
    for key, (part, whole) in _KDR_TOTAL_PERCENTS.items():
        total[key] = round(total[part] * 100 / total[whole]) if total[whole] else 0
    return total


@login_required
def api_kdr(request, year):
    """API для таблицы КДР: строки по ИГК и итоговая строка «ИТОГО»."""
    if year not in YEAR_COL:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        cur.execute(kdr(year))
        rows = _json_rows(cur)
    if rows:
        rows.append(_kdr_total_row(rows))
    return JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})


@login_required
def api_igk_concluded(request, year):
    """API для таблицы заключённых ИГК."""
    return _igk_response(year, CONCLUDED)


@login_required
def api_igk_not_concluded(request, year):
    """API для таблицы незаключённых ИГК."""
    return _igk_response(year, NOT_CONCL)


@login_required
def api_igk_terminated(request, year):
    """API для таблицы расторгнутых ИГК."""
    return _igk_response(year, TERMINATED)


# --- API: История изменений ---


@login_required
def api_history_status(request):
    """API для таблицы изменений статусов."""
    return _json_response(history_status())


@login_required
def api_history_plan(request):
    """API для таблицы изменений планов."""
    return _json_response(history_plan())


@login_required
def api_history_fact(request):
    """API для таблицы изменений фактов."""
    return _json_response(history_fact())


# --- API: Дубликаты ---


@login_required
def api_contract_dupes(request):
    """API для таблицы дубликатов договоров."""
    f = _get_filters(request)
    sql, params = contract_dupes(f["cfo"], f["year"])
    return _json_response(sql, params)


@login_required
def api_contract_dupes_by_order(request):
    """API для таблицы дубликатов по заказу."""
    f = _get_filters(request)
    sql, params = contract_dupes_by_order(f["cfo"], f["year"])
    return _json_response(sql, params)


# --- API: Детализация ИГК ---


@login_required
def api_igk_detail(request, year, igk):
    """API для детализации по конкретному ИГК."""
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    report_type = request.GET.get("type", "concluded")
    statuses = {"concluded": CONCLUDED, "not_concluded": NOT_CONCL}.get(
        report_type, TERMINATED
    )
    return _json_response(igk_detail(year, igk, statuses), [f"%{escape_like(igk)}"])


# --- API: Все договоры ---


@login_required
def api_all_contracts(request):
    """API для реестра всех договоров с фильтрацией."""
    f = _get_filters(request)

    conditions = ["payment_type IS NOT NULL AND TRIM(payment_type) != ''"]
    params = []

    if f["agent"]:
        conditions.append("(c_agent ILIKE %s OR contract ILIKE %s)")
        params.extend([f"%{escape_like(f['agent'])}%"] * 2)

    if f["igk"]:
        conditions.append("igk LIKE %s")
        params.append(f"%{escape_like(f['igk'])}")

    if f["cfo"]:
        # Точное совпадение: раньше было «оканчивается на», и ЦФО 42 находил 142
        conditions.append("TRIM(cfo) = TRIM(%s)")
        params.append(f["cfo"])

    if f["statuses"]:
        conditions.append(f"status IN ({','.join(['%s'] * len(f['statuses']))})")
        params.extend(f["statuses"])
    elif f["raw_statuses"]:
        conditions.append("FALSE")

    if f["year"] in YEAR_COL:
        conditions.append(f"{YEAR_COL[f['year']]} = TRUE")

    where = "WHERE " + " AND ".join(conditions)
    detail_sql, total_sql = all_contracts(where)

    with connection.cursor() as cur:
        cur.execute(detail_sql, params)
        detail = dict_rows(cur)
        cur.execute(total_sql, params)
        total_rows = dict_rows(cur)

    # Ключ подытога — те же поля, что в GROUP BY запроса итогов
    def group_key(row):
        return tuple(row[f] for f in ALL_CONTRACTS_GROUP)

    totals = {group_key(r): r for r in total_rows}

    # Строки позиций договора, сразу за ними — его подытог
    groups = defaultdict(list)
    for row in detail:
        groups[group_key(row)].append(row)

    result = []
    for key, rows in groups.items():
        result.extend(rows)
        if key in totals:
            result.append(totals[key])

    return JsonResponse(
        _to_json_types(result), safe=False, json_dumps_params={"ensure_ascii": False}
    )


# --- API: Заявки на платёж (ФЗД) ---


# Условия фильтрации статусов ЗнП (используются в SQL WHERE)
ZNP_STATUS_CONDITIONS = {
    "not_issued": f"(z.id IS NULL AND {needs_znp()})",
    "in_progress": f"(z.id IS NOT NULL AND z.znp_status IS DISTINCT FROM '{ZNP_APPROVED}')",
    "not_issued_advance": f"(z.id IS NULL AND i.payment_type = '{ADVANCE}' AND {needs_znp()})",
    "not_issued_postpayment": f"(z.id IS NULL AND i.payment_type = '{POSTPAYMENT}' AND {needs_znp()})",
    "advance": f"(z.id IS NOT NULL AND i.payment_type = '{ADVANCE}' AND z.znp_status = '{ZNP_APPROVED}')",
    "advance_paid": f"(z.id IS NOT NULL AND i.payment_type = '{ADVANCE}' AND z.znp_status = '{ZNP_APPROVED}' AND z.fact_sum IS NOT NULL)",
    "postpayment": f"(z.id IS NOT NULL AND i.payment_type = '{POSTPAYMENT}' AND z.znp_status = '{ZNP_APPROVED}')",
    "postpayment_paid": f"(z.id IS NOT NULL AND i.payment_type = '{POSTPAYMENT}' AND z.znp_status = '{ZNP_APPROVED}' AND z.fact_sum IS NOT NULL)",
}


@login_required
def api_znp_list(request):
    """API для реестра заявок на платёж (ФЗД)."""
    f = _get_filters(request)

    conditions = [f"i.status IN ({','.join(['%s'] * len(CONCLUDED))})"]
    params = list(CONCLUDED)

    if f["agent"]:
        conditions.append("(i.c_agent ILIKE %s OR i.contract ILIKE %s)")
        params.extend([f"%{escape_like(f['agent'])}%"] * 2)

    if f["igk"]:
        conditions.append("i.igk LIKE %s")
        params.append(f"%{escape_like(f['igk'])}")

    if f["cfo"]:
        conditions.append("TRIM(i.cfo) = TRIM(%s)")
        params.append(f["cfo"])

    if f["year"] in YEAR_COL:
        conditions.append(f"i.{YEAR_COL[f['year']]} = TRUE")

    status_conditions = [
        ZNP_STATUS_CONDITIONS[s] for s in f["statuses"] if s in ZNP_STATUS_CONDITIONS
    ]
    if status_conditions:
        conditions.append("(" + " OR ".join(status_conditions) + ")")
    elif f["raw_statuses"]:
        conditions.append("FALSE")

    where = "WHERE " + " AND ".join(conditions)
    return _json_response(znp_list(where), params)


# --- API: Заявки на платёж (SAP) ---


@login_required
def api_znp_sap_list(request):
    """API для реестра заявок на платёж (SAP). Использует ORM вместо raw SQL."""
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    date_filter = request.GET.get("date", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]

    qs = ZnpDataSAP.objects.filter(cfo__in=SAP_CFO)

    if agent:
        qs = qs.filter(Q(c_agent__icontains=agent) | Q(reg_num__icontains=agent))
    if igk_filter:
        qs = qs.filter(igk__endswith=igk_filter)
    if cfo_filter:
        qs = qs.filter(cfo=cfo_filter)

    conditions = sap_status_conditions()
    date_ok = valid_date(date_filter)
    status_q = Q()
    for s in statuses:
        if s not in conditions:
            continue
        q = conditions[s]
        if date_ok:
            q = q & Q(**{sap_date_field(s): date_filter})
        status_q = status_q | q
    if status_q:
        qs = qs.filter(status_q)
    elif raw_statuses:
        qs = qs.none()
    elif date_ok:
        qs = qs.filter(created_date=date_filter)

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
            "stage_c",
            "payment_possible",
            "normalize_doc_num",
            "status_key",
        )
    )
    for row in data:
        row["sap_status"] = SAP_STAGE_LABELS[row.pop("status_key")]
        if row.get("igk"):
            row["igk"] = str(row["igk"])[-4:]
        if not row.get("normalize_doc_num"):
            row["payment_possible"] = None
    return JsonResponse(data, safe=False, json_dumps_params={"ensure_ascii": False})


# --- API: Графики ---


def _chart_response(labels, datasets, extra=None):
    """Формирует JSON-ответ для графика Chart.js."""
    payload = {"labels": labels, "datasets": datasets}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


def _stacked_by_cfo(sql, params, stages):
    """Строит данные для стекового графика по ЦФО."""
    with connection.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    totals = {}
    values = {key: {} for key, _ in stages}
    counts = {key: {} for key, _ in stages}
    for cfo, stage, cnt, amount in rows:
        if stage not in values:
            continue
        mln = float(amount or 0) / 1000000
        values[stage][cfo] = mln
        counts[stage][cfo] = int(cnt or 0)
        totals[cfo] = totals.get(cfo, 0) + mln

    labels = sorted(totals, key=lambda cfo: totals[cfo], reverse=True)

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
            "ordinal": True,
            "horizontal": True,
            "stacked": True,
        },
    )


@login_required
def api_chart_contracts(request):
    """API для графика контрактации по ЦФО."""
    year = valid_year(request.GET.get("year"))
    igk = request.GET.get("igk", "").strip()
    if not igk:
        return _chart_response([], [])
    sql, params = contracts_by_cfo(YEAR_COL[str(year)], igk)
    return _stacked_by_cfo(sql, params, CONTRACT_AGE)


@login_required
def api_chart_znp(request):
    """API для графика заявок ФЗД по ЦФО."""
    year = valid_year(request.GET.get("year"))
    igk = request.GET.get("igk", "").strip()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
    if (start or end) and not (valid_date(start) and valid_date(end)):
        return JsonResponse({"error": "недопустимая дата периода"}, status=400)
    if not igk:
        return _chart_response([], [])
    sql, params = znp_by_cfo(YEAR_COL[str(year)], igk, start, end)
    return _stacked_by_cfo(sql, params, ZNP_STAGES)


@login_required
def api_chart_znp_sap(request):
    """API для графика заявок SAP по ЦФО."""
    igk = request.GET.get("igk", "").strip()
    if not igk:
        return _chart_response([], [])
    sql, params = znp_sap_by_cfo(igk)
    return _stacked_by_cfo(sql, params, SAP_STAGES)
