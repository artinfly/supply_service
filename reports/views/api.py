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


def _to_json_types(rows):
    for row in rows:
        for k, v in row.items():
            if isinstance(v, Decimal):
                row[k] = int(v) if v == v.to_integral_value() else float(v)
    return rows


def _json_rows(cur):
    cols = [c[0] for c in cur.description]
    return _to_json_types([dict(zip(cols, r)) for r in cur.fetchall()])


def _json_response(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return JsonResponse(
            _json_rows(cur), safe=False, json_dumps_params={"ensure_ascii": False}
        )


def _igk_response(year, statuses):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        cur.execute(igk_stat(yc, statuses))
        rows = _json_rows(cur)
        cur.execute(igk_stat_total(yc, statuses))
        rows.append(dict(zip([c[0] for c in cur.description], cur.fetchone())))
    return JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})


@login_required
def api_kdr(request, year):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
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
    sql, params = contract_dupes(
        request.GET.get("cfo", "").strip(),
        request.GET.get("year", "").strip(),
    )
    return _json_response(sql, params)


@login_required
def api_contract_dupes_by_order(request):
    sql, params = contract_dupes_by_order(
        request.GET.get("cfo", "").strip(),
        request.GET.get("year", "").strip(),
    )
    return _json_response(sql, params)


@login_required
def api_igk_detail(request, year, igk):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    report_type = request.GET.get("type", "concluded")
    statuses = {"concluded": CONCLUDED, "not_concluded": NOT_CONCL}.get(
        report_type, TERMINATED
    )
    return _json_response(igk_detail(year, igk, statuses), [f"%{escape_like(igk)}"])


@login_required
def api_all_contracts(request):
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]
    year_filter = request.GET.get("year", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()

    conditions = ["payment_type IS NOT NULL AND TRIM(payment_type) != ''"]
    params = []
    if agent:
        conditions.append("(c_agent ILIKE %s OR contract ILIKE %s)")
        params.append(f"%{escape_like(agent)}%")
        params.append(f"%{escape_like(agent)}%")
    if igk_filter:
        conditions.append("igk LIKE %s")
        params.append(f"%{escape_like(igk_filter)}")
    if cfo_filter:
        conditions.append("cfo LIKE %s")
        params.append(f"%{escape_like(cfo_filter)}")
    if statuses:
        conditions.append(f"status IN ({','.join(['%s'] * len(statuses))})")
        params.extend(statuses)
    elif raw_statuses:
        conditions.append("FALSE")
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

    return JsonResponse(
        _to_json_types(result), safe=False, json_dumps_params={"ensure_ascii": False}
    )


ZNP_STATUS_CONDITIONS = {
    "not_issued": f"(z.id IS NULL AND {needs_znp()})",
    "in_progress": f"(z.id IS NOT NULL AND z.znp_status IS DISTINCT FROM '{ZNP_APPROVED}')",
    "not_issued_advance": (
        f"(z.id IS NULL AND i.payment_type = '{ADVANCE}'" f" AND {needs_znp()})"
    ),
    "not_issued_postpayment": (
        f"(z.id IS NULL AND i.payment_type = '{POSTPAYMENT}'" f" AND {needs_znp()})"
    ),
    "advance": (
        f"(z.id IS NOT NULL AND i.payment_type = '{ADVANCE}'"
        f" AND z.znp_status = '{ZNP_APPROVED}')"
    ),
    "advance_paid": (
        f"(z.id IS NOT NULL AND i.payment_type = '{ADVANCE}'"
        f" AND z.znp_status = '{ZNP_APPROVED}' AND z.fact_sum IS NOT NULL)"
    ),
    "postpayment": (
        f"(z.id IS NOT NULL AND i.payment_type = '{POSTPAYMENT}'"
        f" AND z.znp_status = '{ZNP_APPROVED}')"
    ),
    "postpayment_paid": (
        f"(z.id IS NOT NULL AND i.payment_type = '{POSTPAYMENT}'"
        f" AND z.znp_status = '{ZNP_APPROVED}' AND z.fact_sum IS NOT NULL)"
    ),
}


@login_required
def api_znp_list(request):
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    year_filter = request.GET.get("year", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]

    conditions = [f"i.status IN ({','.join(['%s'] * len(CONCLUDED))})"]
    params = list(CONCLUDED)
    if agent:
        conditions.append("(i.c_agent ILIKE %s OR i.contract ILIKE %s)")
        params.append(f"%{escape_like(agent)}%")
        params.append(f"%{escape_like(agent)}%")
    if igk_filter:
        conditions.append("i.igk LIKE %s")
        params.append(f"%{escape_like(igk_filter)}")
    if cfo_filter:
        conditions.append("i.cfo LIKE %s")
        params.append(f"%{escape_like(cfo_filter)}")
    if year_filter in YEAR_COL:
        conditions.append(f"i.{YEAR_COL[year_filter]} = TRUE")
    status_conditions = [
        ZNP_STATUS_CONDITIONS[s] for s in statuses if s in ZNP_STATUS_CONDITIONS
    ]
    if status_conditions:
        conditions.append("(" + " OR ".join(status_conditions) + ")")
    elif raw_statuses:
        conditions.append("FALSE")

    where = "WHERE " + " AND ".join(conditions)
    return _json_response(znp_list(where), params)


@login_required
def api_znp_sap_list(request):
    agent = request.GET.get("agent", "").strip()
    igk_filter = request.GET.get("igk", "").strip()
    cfo_filter = request.GET.get("cfo", "").strip()
    raw_statuses = request.GET.getlist("status")
    statuses = [s for s in raw_statuses if s]

    qs = ZnpDataSAP.objects.filter(cfo__in=SAP_CFO)
    if agent:
        qs = qs.filter(Q(c_agent__icontains=agent) | Q(reg_num__icontains=agent))
    if igk_filter:
        qs = qs.filter(igk__icontains=igk_filter)
    if cfo_filter:
        qs = qs.filter(cfo__icontains=cfo_filter)

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
    return JsonResponse(data, safe=False, json_dumps_params={"ensure_ascii": False})


def _chart_response(labels, datasets, extra=None):
    payload = {"labels": labels, "datasets": datasets}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


def _stacked_by_cfo(sql, params, stages, title):
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
    igk = request.GET.get("igk", "").strip()
    sql, params = znp_sap_by_cfo(igk)
    return _stacked_by_cfo(sql, params, SAP_STAGES, "Заявки SAP по ЦФО и этапам")
