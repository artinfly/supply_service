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
    all_contracts,
    contract_dupes,
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
MONTH_KEYS = [f"{m:02d}" for m in range(1, 13)]


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
    "advance": "(z.id IS NOT NULL AND i.payment_type = 'Аванс')",
    "advance_paid": "(z.id IS NOT NULL AND i.payment_type = 'Аванс' AND z.fact_sum IS NOT NULL)",
    "postpayment": "(z.id IS NOT NULL AND i.payment_type = 'Постоплата')",
    "postpayment_paid": "(z.id IS NOT NULL AND i.payment_type = 'Постоплата' AND z.fact_sum IS NOT NULL)",
}


@login_required
def api_znp_list(request):
    agent = request.GET.get("agent", "").strip()
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
    # мусор в ?year= не должен ронять страницу
    try:
        return int(request.GET.get("year", ""))
    except (TypeError, ValueError):
        return _date.today().year


def _months_frame():
    """Пустой каркас на 12 месяцев — чтобы график не съезжал на дырах."""
    return {key: 0.0 for key in MONTH_KEYS}


def _chart_response(datasets, extra=None):
    payload = {"labels": MONTHS, "datasets": datasets}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


@login_required
def api_chart_contracts(request):
    """Авансы по месяцам: план и факт, в млн рублей."""
    year = _resolve_chart_year(request)
    igk = request.GET.get("igk", "").strip()
    plan, fact = _months_frame(), _months_frame()

    if igk:
        sql, params = contracts_monthly(year, igk)
        with connection.cursor() as cur:
            cur.execute(sql, params)
            for month, plan_sum, fact_sum in cur.fetchall():
                if month in plan:
                    plan[month] = float(plan_sum or 0) / 1000000
                    fact[month] = float(fact_sum or 0) / 1000000

    return _chart_response(
        [
            {"label": "План", "data": [plan[k] for k in MONTH_KEYS]},
            {"label": "Факт", "data": [fact[k] for k in MONTH_KEYS]},
        ],
        {"unit": "млн ₽", "title": f"Авансы по месяцам, {year}"},
    )


@login_required
def api_chart_znp(request):
    """ЗНП (ФЗД) по месяцам: плановые платежи против прошедших, в млн рублей."""
    year = _resolve_chart_year(request)
    igk = request.GET.get("igk", "").strip()
    plan, fact = _months_frame(), _months_frame()

    if igk:
        sql, params = znp_monthly(year, igk)
        with connection.cursor() as cur:
            cur.execute(sql, params)
            for month, plan_sum, fact_sum in cur.fetchall():
                if month in plan:
                    plan[month] = float(plan_sum or 0) / 1000000
                    fact[month] = float(fact_sum or 0) / 1000000

    return _chart_response(
        [
            {"label": "План платежа", "data": [plan[k] for k in MONTH_KEYS]},
            {"label": "Оплачено", "data": [fact[k] for k in MONTH_KEYS]},
        ],
        {"unit": "млн ₽", "title": f"Заявки на платёж по месяцам, {year}"},
    )


# порядок важен: этапы идут по возрастанию, и график красится
# одноцветной шкалой от светлого к тёмному
SAP_CHART_STAGES = [
    ("stage_e", "Передано в 18 отдел"),
    ("stage_f", "Подтверждено 18 отделом"),
    ("payment_possible", "Возможна оплата"),
]


@login_required
def api_chart_znp_sap(request):
    """ЗНП (SAP) по месяцам: сколько заявок прошло каждый этап."""
    year = _resolve_chart_year(request)
    igk = request.GET.get("igk", "").strip()

    counts = {column: _months_frame() for column, _ in SAP_CHART_STAGES}
    amounts = {column: _months_frame() for column, _ in SAP_CHART_STAGES}

    sql, params = znp_sap_monthly(year, igk)
    with connection.cursor() as cur:
        cur.execute(sql, params)
        for month, stage, cnt, amount in cur.fetchall():
            if stage in counts and month in counts[stage]:
                counts[stage][month] = float(cnt or 0)
                amounts[stage][month] = float(amount or 0) / 1000000

    return _chart_response(
        [
            {
                "label": label,
                "data": [counts[column][k] for k in MONTH_KEYS],
                "amounts": [amounts[column][k] for k in MONTH_KEYS],
            }
            for column, label in SAP_CHART_STAGES
        ],
        {"unit": "шт", "ordinal": True, "title": f"Этапы заявок по месяцам, {year}"},
    )
