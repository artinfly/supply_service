"""
JSON API для таблиц и графиков.

Страницы отдают только каркас, данные подгружаются запросами к этим эндпоинтам.
Все данные берутся через сырой SQL из services/queries.py и services/charts.py.
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

# --- Вспомогательные функции ---


def _to_json_types(rows):
    """Конвертирует Decimal в int/float для сериализации в JSON."""
    for row in rows:
        for k, v in row.items():
            if isinstance(v, Decimal):
                row[k] = int(v) if v == v.to_integral_value() else float(v)
    return rows


def _json_rows(cur):
    """Преобразует результат курсора в список словарей."""
    cols = [c[0] for c in cur.description]
    return _to_json_types([dict(zip(cols, r)) for r in cur.fetchall()])


def _json_response(sql, params=None):
    """Выполняет SQL и возвращает JSON со списком строк."""
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return JsonResponse(
            _json_rows(cur), safe=False, json_dumps_params={"ensure_ascii": False}
        )


def _igk_response(year, statuses):
    """Ответ для страниц ИГК: детальные строки + итоговая строка."""
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        cur.execute(igk_stat(yc, statuses))
        rows = _json_rows(cur)
        cur.execute(igk_stat_total(yc, statuses))
        rows.append(dict(zip([c[0] for c in cur.description], cur.fetchone())))
    return JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})


def _get_filters(request):
    """Читает общие параметры фильтров из GET-запроса."""
    return {
        "agent": request.GET.get("agent", "").strip(),
        "igk": request.GET.get("igk", "").strip(),
        "cfo": request.GET.get("cfo", "").strip(),
        "year": request.GET.get("year", "").strip(),
        "statuses": [s for s in request.GET.getlist("status") if s],
        "raw_statuses": request.GET.getlist("status"),
    }


# --- Реестры по годам: КДР и ИГК ---


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


# --- История изменений ---


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


# --- Дубликаты договоров ---


@login_required
def api_contract_dupes(request):
    """Данные для таблицы «Дубликаты договоров» (полные повторы строк)."""
    f = _get_filters(request)
    sql, params = contract_dupes(f["cfo"], f["year"])
    return _json_response(sql, params)


@login_required
def api_contract_dupes_by_order(request):
    """Данные для таблицы «Дубликаты по заказу» (по ИГК, предмету, заказу)."""
    f = _get_filters(request)
    sql, params = contract_dupes_by_order(f["cfo"], f["year"])
    return _json_response(sql, params)


# --- Детализация по ИГК ---


@login_required
def api_igk_detail(request, year, igk):
    """Детальная страница по одному ИГК за год."""
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    report_type = request.GET.get("type", "concluded")
    statuses = {"concluded": CONCLUDED, "not_concluded": NOT_CONCL}.get(
        report_type, TERMINATED
    )
    return _json_response(igk_detail(year, igk, statuses), [f"%{escape_like(igk)}"])


# --- Реестр всех договоров ---


@login_required
def api_all_contracts(request):
    """Реестр всех договоров с фильтрами."""
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
        conditions.append("cfo LIKE %s")
        params.append(f"%{escape_like(f['cfo'])}")

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
        cols = [c[0] for c in cur.description]
        detail = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(total_sql, params)
        totals = {(r[0], r[2], r[6]): dict(zip(cols, r)) for r in cur.fetchall()}

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


# --- Реестр заявок ФЗД ---

# Условия фильтров по статусам заявок ФЗД.
# ВАЖНО: при изменении статусов синхронизировать с services/dashboards.py
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
    """Реестр заявок ФЗД с фильтрами."""
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
        conditions.append("i.cfo LIKE %s")
        params.append(f"%{escape_like(f['cfo'])}")

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


# --- Реестр заявок SAP ---


@login_required
def api_znp_sap_list(request):
    """Реестр заявок SAP с фильтрами (данные через ORM)."""
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
        qs = qs.filter(igk__icontains=igk_filter)
    if cfo_filter:
        qs = qs.filter(cfo__icontains=cfo_filter)
    if valid_date(date_filter):
        qs = qs.filter(payment_possible=date_filter)

    conditions = sap_status_conditions()
    status_q = Q()
    for s in statuses:
        if s in conditions:
            status_q |= conditions[s]
    if status_q:
        qs = qs.filter(status_q)
    elif raw_statuses:
        qs = qs.none()

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
    for row in data:
        row["sap_status"] = SAP_STAGE_LABELS[row.pop("status_key")]
        if row.get("igk"):
            row["igk"] = str(row["igk"])[-4:]
        # payment_possible показываем только для оплаченных заявок
        if not row.get("normalize_doc_num"):
            row["payment_possible"] = None
    return JsonResponse(data, safe=False, json_dumps_params={"ensure_ascii": False})


# --- Графики для сводок ---


def _chart_response(labels, datasets, extra=None):
    """Формирует ответ для Chart.js."""
    payload = {"labels": labels, "datasets": datasets}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


def _stacked_by_cfo(sql, params, stages, title):
    """
    Универсальный сборщик стековых графиков по ЦФО.
    Ось X — ЦФО (по убыванию суммы), сегменты стека — стадии.
    """
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
            "title": title,
        },
    )


@login_required
def api_chart_contracts(request):
    """График «Незаключённые по ЦФО и давности срока» для dashboard."""
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
    """График «Заявки по ЦФО и стадиям» для сводки заявок ФЗД."""
    year = valid_year(request.GET.get("year"))
    igk = request.GET.get("igk", "").strip()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
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
    """График «Заявки SAP по ЦФО и этапам» для сводки заявок SAP."""
    igk = request.GET.get("igk", "").strip()
    sql, params = znp_sap_by_cfo(igk)
    return _stacked_by_cfo(sql, params, SAP_STAGES, "Заявки SAP по ЦФО и этапам")
