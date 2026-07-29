from collections import defaultdict
from datetime import date as _date

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Q
from django.http import JsonResponse

from ..models import ZnpDataSAP
from ..services.queries import (
    CONCLUDED,
    NOT_CONCL,
    TERMINATED,
    YEAR_COL,
    YEARS,
    all_contracts,
    contract_dupes,
    contract_dupes_by_order,
    history_fact,
    history_plan,
    history_status,
    igk_detail,
    igk_stat,
    igk_stat_total,
    kdr,
    znp_list,
)
from ..services.sap_status import SAP_STATUS_CONDITIONS, sap_status
from ..services.timeseries import contracts_monthly, znp_monthly, znp_sap_monthly

MONTHS = [
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
]


def _month_axis(keys):
    """Непрерывный ряд год-месяцев от первого до последнего из keys.

    Дыры внутри диапазона заполняются: без этого соседние столбцы оказались бы
    рядом, хотя между ними полгода. Ключ — "ГГГГ.ММ", подпись — "мес ГГ".
    """
    parsed = sorted({k for k in keys if k and len(k) == 7})
    if not parsed:
        return [], []
    start, end = parsed[0], parsed[-1]
    y0, m0 = int(start[:4]), int(start[5:7])
    y1, m1 = int(end[:4]), int(end[5:7])

    axis = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        axis.append(f"{y}.{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    labels = [f"{MONTHS[int(k[5:7]) - 1]} {k[2:4]}" for k in axis]
    return axis, labels


def _json_rows(cur):
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "__float__"):
                row[k] = float(v)
    return rows


def _json_response(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return JsonResponse(
            _json_rows(cur), safe=False, json_dumps_params={"ensure_ascii": False}
        )


def _escape_like(value):
    # без экранирования % и _ в значении фильтра работают как маски LIKE
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _igk_response(year, statuses):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "invalid year"}, status=400)
    with connection.cursor() as cur:
        cur.execute(igk_stat(yc, statuses))
        rows = _json_rows(cur)
        cur.execute(igk_stat_total(yc, statuses))
        rows.append(dict(zip([c[0] for c in cur.description], cur.fetchone())))
    return JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})


@login_required
def api_kdr(request, year):
    # без проверки неизвестный год превращается в "None=TRUE" внутри SQL
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "invalid year"}, status=400)
    return _json_response(kdr(year))


@login_required
def api_igk_concluded(request, year):
    return _igk_response(year, CONCLUDED)


@login_required
def api_igk_not_concluded(request, year):
    return _igk_response(year, NOT_CONCL)


@login_required
def api_igk_terminated(request, year):
    return _igk_response(year, TERMINATED)


@login_required
def api_history_status(request):
    return _json_response(history_status())


@login_required
def api_history_plan(request):
    return _json_response(history_plan())


@login_required
def api_history_fact(request):
    return _json_response(history_fact())


@login_required
def api_contract_dupes(request):
    return _json_response(contract_dupes())


@login_required
def api_contract_dupes_by_order(request):
    return _json_response(contract_dupes_by_order())


@login_required
def api_igk_detail(request, year, igk):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "invalid year"}, status=400)
    report_type = request.GET.get("type", "concluded")
    statuses = {"concluded": CONCLUDED, "not_concluded": NOT_CONCL}.get(
        report_type, TERMINATED
    )
    return _json_response(igk_detail(year, igk, statuses), [f"%{igk}"])


@login_required
def api_all_contracts(request):
    agent = request.GET.get("agent", "").strip()
    contract_filter = request.GET.get("contract", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    statuses = request.GET.getlist("status")
    year_filter = request.GET.get("year", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()

    conditions = ["payment_type IS NOT NULL AND TRIM(payment_type) != ''"]
    params = []
    if agent:
        conditions.append("(c_agent ILIKE %s OR contract ILIKE %s)")
        params.append(f"%{agent}%")
        params.append(f"%{agent}%")
    if igk_filter:
        conditions.append("igk LIKE %s")
        params.append(f"%{_escape_like(igk_filter)}")
    if cfo_filter:
        conditions.append("cfo LIKE %s")
        params.append(f"%{_escape_like(cfo_filter)}")
    if contract_filter:
        conditions.append("contract ILIKE %s")
        params.append(f"%{contract_filter}%")
    if statuses:
        conditions.append(f"status IN ({','.join(['%s'] * len(statuses))})")
        params.extend(statuses)
    if year_filter in YEAR_COL:
        conditions.append(f"{YEAR_COL[year_filter]} = TRUE")

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

    for row in result:
        for k, v in row.items():
            if hasattr(v, "__float__"):
                row[k] = float(v)
    return JsonResponse(result, safe=False, json_dumps_params={"ensure_ascii": False})


ZNP_STATUS_CONDITIONS = {
    "not_issued": "z.id IS NULL",
    "not_issued_advance": "(z.id IS NULL AND i.payment_type = 'Аванс')",
    "not_issued_postpayment": "(z.id IS NULL AND i.payment_type = 'Постоплата')",
    "advance": "(z.id IS NOT NULL AND i.payment_type = 'Аванс')",
    "advance_paid": "(z.id IS NOT NULL AND i.payment_type = 'Аванс' AND z.fact_sum IS NOT NULL)",
    "postpayment": "(z.id IS NOT NULL AND i.payment_type = 'Постоплата')",
    "postpayment_paid": "(z.id IS NOT NULL AND i.payment_type = 'Постоплата' AND z.fact_sum IS NOT NULL)",
}


@login_required
def api_znp_list(request):
    agent = request.GET.get("agent", "").strip()
    contract_filter = request.GET.get("contract", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    year_filter = request.GET.get("year", "").strip()
    statuses = request.GET.getlist("status")

    conditions = [f"i.status IN ({','.join(['%s'] * len(CONCLUDED))})"]
    params = list(CONCLUDED)
    if agent:
        conditions.append("(i.c_agent ILIKE %s OR i.contract ILIKE %s)")
        params.append(f"%{agent}%")
        params.append(f"%{agent}%")
    if igk_filter:
        conditions.append("i.igk LIKE %s")
        params.append(f"%{_escape_like(igk_filter)}")
    if cfo_filter:
        conditions.append("i.cfo LIKE %s")
        params.append(f"%{_escape_like(cfo_filter)}")
    if contract_filter:
        conditions.append("i.contract ILIKE %s")
        params.append(f"%{contract_filter}%")
    if year_filter in YEAR_COL:
        conditions.append(f"i.{YEAR_COL[year_filter]} = TRUE")
    status_conditions = [
        ZNP_STATUS_CONDITIONS[s] for s in statuses if s in ZNP_STATUS_CONDITIONS
    ]
    if status_conditions:
        conditions.append("(" + " OR ".join(status_conditions) + ")")

    where = "WHERE " + " AND ".join(conditions)
    return _json_response(znp_list(where), params)


@login_required
def api_znp_sap_list(request):
    from .pages import SAP_STAGE_LABELS

    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    statuses = request.GET.getlist("status")

    qs = ZnpDataSAP.objects.all()
    if agent:
        qs = qs.filter(Q(c_agent__icontains=agent) | Q(reg_num__icontains=agent))
    if igk_filter:
        qs = qs.filter(igk__icontains=igk_filter)
    if cfo_filter:
        qs = qs.filter(cfo__icontains=cfo_filter)

    status_q = Q()
    for s in statuses:
        if s in SAP_STATUS_CONDITIONS:
            status_q |= SAP_STATUS_CONDITIONS[s]
    # проверяем сам status_q, а не statuses: при неизвестном значении фильтра
    # statuses непустой, но условий в нём нет — фильтровать нечем
    if status_q:
        qs = qs.filter(status_q)

    data = list(
        qs.order_by("cfo", "reg_num").values(
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
        )
    )
    for row in data:
        status = sap_status(
            row["stage_e"],
            row["stage_f"],
            row["normalize_doc_num"],
        )
        row["sap_status"] = SAP_STAGE_LABELS[status]
    return JsonResponse(data, safe=False, json_dumps_params={"ensure_ascii": False})


def _resolve_chart_year(request):
    """Год из селектора страницы; мусор в ?year= не должен ронять график."""
    try:
        year = int(request.GET.get("year", ""))
    except (TypeError, ValueError):
        year = _date.today().year
    return year if year in YEARS else YEARS[-1]


def _chart_response(labels, datasets, extra=None):
    payload = {"labels": labels, "datasets": datasets}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


def _two_series(sql, params, first, second, unit, title, stacked=False):
    """Два ряда сумм в млн рублей по общей оси год-месяцев."""
    with connection.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    axis, labels = _month_axis(row[0] for row in rows)
    a = dict.fromkeys(axis, 0.0)
    b = dict.fromkeys(axis, 0.0)
    for ym, first_sum, second_sum in rows:
        if ym in a:
            a[ym] = float(first_sum or 0) / 1000000
            b[ym] = float(second_sum or 0) / 1000000

    return _chart_response(
        labels,
        [
            {"label": first, "data": [a[k] for k in axis]},
            {"label": second, "data": [b[k] for k in axis]},
        ],
        {"unit": unit, "title": title, "stacked": stacked},
    )


@login_required
def api_chart_contracts(request):
    """Контрактация по месяцам графика платежей: заключено и незаключённое."""
    year = _resolve_chart_year(request)
    igk = request.GET.get("igk", "").strip()
    if not igk:
        return _chart_response([], [])
    sql, params = contracts_monthly(YEAR_COL[str(year)], igk)
    return _two_series(
        sql,
        params,
        "Заключено",
        "Не заключено",
        "млн ₽",
        f"Суммы договоров по месяцам графика платежей, ГодИГК {year}",
        stacked=True,
    )


@login_required
def api_chart_znp(request):
    """ЗНП (ФЗД) по месяцам: оформлено и оплачено."""
    year = _resolve_chart_year(request)
    igk = request.GET.get("igk", "").strip()
    if not igk:
        return _chart_response([], [])
    sql, params = znp_monthly(YEAR_COL[str(year)], igk)
    return _two_series(
        sql,
        params,
        "Оформлено",
        "Оплачено",
        "млн ₽",
        f"Заявки на платёж по месяцам, ГодИГК {year}",
    )


# порядок важен: этапы идут по возрастанию, график красится одноцветной
# шкалой от светлого к тёмному
SAP_CHART_STAGES = [
    ("stage_e", "Передано в 18 отдел"),
    ("stage_f", "Подтверждено 18 отделом"),
    ("payment_possible", "Возможна оплата"),
]


@login_required
def api_chart_znp_sap(request):
    """ЗНП (SAP) по месяцам: сколько заявок прошло каждый этап согласования."""
    igk = request.GET.get("igk", "").strip()
    sql, params = znp_sap_monthly(igk)
    with connection.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    axis, labels = _month_axis(row[0] for row in rows)
    counts = {column: dict.fromkeys(axis, 0.0) for column, _ in SAP_CHART_STAGES}
    amounts = {column: dict.fromkeys(axis, 0.0) for column, _ in SAP_CHART_STAGES}
    for ym, stage, cnt, amount in rows:
        if stage in counts and ym in counts[stage]:
            counts[stage][ym] = float(cnt or 0)
            amounts[stage][ym] = float(amount or 0) / 1000000

    return _chart_response(
        labels,
        [
            {
                "label": label,
                "data": [counts[column][k] for k in axis],
                "amounts": [amounts[column][k] for k in axis],
            }
            for column, label in SAP_CHART_STAGES
        ],
        {"unit": "шт", "ordinal": True, "title": "Этапы согласования по месяцам"},
    )
