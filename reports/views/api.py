from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse

from ..services.queries import (
    CONCLUDED, NOT_CONCL, TERMINATED, YEAR_COL,
    kdr, igk_stat, igk_stat_total, history_status,
    history_plan, history_fact, contract_dupes,
    igk_detail, contracts_by_agent, all_contracts,
)


def _json_rows(cur):
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for row in rows:
        for k, v in row.items():
            if hasattr(v, '__float__'):
                row[k] = float(v)
    return rows


def _json_response(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return JsonResponse(_json_rows(cur), safe=False, json_dumps_params={'ensure_ascii': False})


def _igk_response(year, statuses):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({'error': 'invalid year'}, status=400)
    with connection.cursor() as cur:
        cur.execute(igk_stat(yc, statuses))
        rows = _json_rows(cur)
        cur.execute(igk_stat_total(yc, statuses))
        rows.append(dict(zip([c[0] for c in cur.description], cur.fetchone())))
    return JsonResponse(rows, safe=False, json_dumps_params={'ensure_ascii': False})


@login_required
def api_kdr(request, year):
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
        return JsonResponse({'error': 'invalid year'}, status=400)
    report_type = request.GET.get('type', 'concluded')
    statuses = {'concluded': CONCLUDED, 'not_concluded': NOT_CONCL}.get(report_type, TERMINATED)
    return _json_response(igk_detail(year, igk, statuses), [f'%{igk}'])


@login_required
def api_contracts_by_agent(request):
    year = request.GET.get('year', '').strip()
    agent = request.GET.get('agent', '').strip()
    yc = YEAR_COL.get(year)
    if not yc or not agent:
        return JsonResponse([], safe=False)
    return _json_response(contracts_by_agent(year), [f'%{agent}%'])


@login_required
def api_all_contracts(request):
    agent = request.GET.get('agent', '').strip()
    igk_filter = request.GET.get('igk', '').strip()
    statuses = request.GET.getlist('status')
    year_filter = request.GET.get('year', '').strip()

    conditions = ["payment_type IS NOT NULL AND TRIM(payment_type) != ''"]
    params = []
    if agent:
        conditions.append("c_agent ILIKE %s")
        params.append(f'%{agent}%')
    if igk_filter:
        conditions.append("igk LIKE %s")
        params.append(f'%{igk_filter}')
    if statuses:
        conditions.append(f"status IN ({','.join(['%s'] * len(statuses))})")
        params.extend(statuses)
    if year_filter in YEAR_COL:
        conditions.append(f"{YEAR_COL[year_filter]} = TRUE")

    where = 'WHERE ' + ' AND '.join(conditions)
    detail_sql, total_sql, total_params = all_contracts(where, params)

    with connection.cursor() as cur:
        cur.execute(detail_sql, params)
        cols = [c[0] for c in cur.description]
        detail = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(total_sql, params)
        totals = {(r[0], r[2], r[6]): dict(zip(cols, r)) for r in cur.fetchall()}

    groups = defaultdict(list)
    for row in detail:
        groups[(row['igk'], row['contract'], row['order'])].append(row)

    result = []
    for key, rows in groups.items():
        result.extend(rows)
        if key in totals:
            result.append(totals[key])

    for row in result:
        for k, v in row.items():
            if hasattr(v, '__float__'):
                row[k] = float(v)
    return JsonResponse(result, safe=False, json_dumps_params={'ensure_ascii': False})