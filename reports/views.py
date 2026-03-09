from django.http import JsonResponse
from django.shortcuts import render
from django.db import connection
from datetime import date, timedelta

CONCLUDED  = ('Исполняется', 'Возвращен на уточнение', 'На согласовании', 'Подписан', 'На утверждении')
NOT_CONCL  = ('Черновик',)
TERMINATED = ('Расторгнут',)

YEARS    = [2025, 2026, 2027]
YEAR_COL = {str(y): f'y{str(y)[2:]}' for y in YEARS}


def _years_context():
    return {'years': YEARS, 'year_cols': [(y, f"y{str(y)[2:]}") for y in YEARS]}


def index(request):
    return render(request, 'reports/index.html', _years_context())

def kdr_table(request, year):
    ctx = _years_context()
    ctx['year'] = year
    return render(request, 'reports/kdr_table.html', ctx)

def igk_concluded_table(request, year):
    ctx = _years_context()
    ctx.update({'year': year, 'report_type': 'concluded', 'title': f'Заключённые ИГК {year}'})
    return render(request, 'reports/igk_table.html', ctx)

def igk_not_concluded_table(request, year):
    ctx = _years_context()
    ctx.update({'year': year, 'report_type': 'not_concluded', 'title': f'Незаключённые ИГК {year}'})
    return render(request, 'reports/igk_table.html', ctx)

def igk_terminated_table(request, year):
    ctx = _years_context()
    ctx.update({'year': year, 'report_type': 'terminated', 'title': f'Расторгнутые ИГК {year}'})
    return render(request, 'reports/igk_table.html', ctx)

def day_stat_only_igk_table(request):
    return render(request, 'reports/day_stat_only_igk.html', _years_context())

def day_stat_with_cfo_table(request):
    return render(request, 'reports/day_stat_with_cfo.html', _years_context())

def all_pps_table(request):
    return render(request, 'reports/all_pps.html', _years_context())

def all_contracts_table(request):
    with connection.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT RIGHT(igk, 4)
            FROM igk_stat_data
            WHERE igk IS NOT NULL
            ORDER BY RIGHT(igk, 4)
        """)
        igk_list = [row[0] for row in cur.fetchall()]
    ctx = _years_context()
    ctx['igk_list'] = igk_list
    ctx['concluded_statuses']  = list(CONCLUDED)
    ctx['not_concl_statuses']  = list(NOT_CONCL)
    ctx['terminated_statuses'] = list(TERMINATED)
    return render(request, 'reports/all_contracts.html', ctx)

def history_status_table(request):
    return render(request, 'reports/history_status.html', _years_context())

def history_plan_table(request):
    return render(request, 'reports/history_plan.html', _years_context())

def history_fact_table(request):
    return render(request, 'reports/history_fact.html', _years_context())

def contract_dupes_table(request):
    return render(request, 'reports/contract_dupes.html', _years_context())


def _query_to_json(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    data = []
    for row in rows:
        record = {}
        for col, val in zip(cols, row):
            if hasattr(val, '__float__'):
                val = float(val)
            record[col] = val
        data.append(record)
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False})


def api_kdr(request, year):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({'error': 'invalid year'}, status=400)

    cl = "'" + "','".join(CONCLUDED) + "'"
    nl = "'" + "','".join(NOT_CONCL) + "'"

    sql = f"""
    SELECT
        igk,
        (SELECT COUNT(DISTINCT contract) FROM igk_stat_data p2
         WHERE p2.igk = p.igk AND "order" IS NOT NULL AND "order" != '') AS orders,
        ROUND(CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND "order" != ''), 0) / 1000000.0 AS numeric), 2) AS order_sum,
        (SELECT COUNT(DISTINCT contract) FROM igk_stat_data
         WHERE igk = p.igk AND "order" != '' AND status IN ({cl})) AS count_concluded,
        ROUND(CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
             WHERE igk = p.igk AND "order" != '' AND status IN ({cl})), 0) / 1000000.0 AS numeric), 2) AS concluded_order_sum,
        (SELECT COUNT(DISTINCT contract) FROM igk_stat_data
         WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status != 'Расторгнут') AS count_curr_year,
        ROUND(CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status != 'Расторгнут'), 0) / 1000000.0 AS numeric), 2) AS order_sum_curr_year,
        (SELECT COUNT(DISTINCT contract) FROM igk_stat_data
         WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status IN ({cl})) AS count_concluded_curr_year,
        ROUND(CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status IN ({cl})), 0) / 1000000.0 AS numeric), 2) AS concluded_order_sum_curr_year,
        ROUND(CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND payment_type = 'Аванс' AND status != 'Расторгнут'), 0) / 1000000.0 AS numeric), 2) AS pp_sum_plan,
        ROUND(CAST(COALESCE((SELECT SUM(fact) FROM igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND payment_type = 'Аванс' AND status != 'Расторгнут'), 0) / 1000000.0 AS numeric), 2) AS pp_sum_fact,
        (SELECT COUNT(DISTINCT contract) FROM igk_stat_data
         WHERE igk = p.igk AND "order" != '' AND status IN ({nl}) AND {yc} = TRUE) AS count_not_concluded_curr_year,
        ROUND(CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status IN ({nl})), 0) / 1000000.0 AS numeric), 2) AS not_concluded_order_sum_curr_year,
        CASE WHEN (SELECT COUNT(DISTINCT contract) FROM igk_stat_data
                   WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status != 'Расторгнут') = 0 THEN 0
             ELSE CAST((SELECT COUNT(DISTINCT contract) FROM igk_stat_data
                        WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status IN ({cl})) * 100.0
                  / NULLIF((SELECT COUNT(DISTINCT contract) FROM igk_stat_data
                        WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status != 'Расторгнут'), 0) AS int)
        END AS count_concluded_percent_curr_year,
        CASE WHEN COALESCE((SELECT SUM(plan) FROM igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status != 'Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE((SELECT SUM(plan) FROM igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status IN ({cl})), 0) * 100.0
                  / NULLIF((SELECT SUM(plan) FROM igk_stat_data
                        WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND status != 'Расторгнут'), 0) AS int)
        END AS order_sum_percent_curr_year,
        CASE WHEN COALESCE((SELECT SUM(plan) FROM igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND payment_type = 'Аванс' AND status != 'Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE((SELECT SUM(fact) FROM igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND payment_type = 'Аванс' AND status != 'Расторгнут'), 0)
                  / NULLIF((SELECT SUM(plan) FROM igk_stat_data
                        WHERE igk = p.igk AND "order" IS NOT NULL AND {yc} = TRUE AND payment_type = 'Аванс' AND status != 'Расторгнут'), 0) * 100 AS int)
        END AS pp_percent
    FROM igk_stat_data p
    GROUP BY igk
    ORDER BY igk
    """
    return _query_to_json(sql)


def _igk_stat_sql(yc, statuses):
    sl = "'" + "','".join(statuses) + "'"
    return f"""
    SELECT igk,
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) * 100.0 / NULLIF(SUM(plan), 0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) * 100.0 / NULLIF(SUM(plan), 0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN plan END), 0) - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN fact END), 0) AS numeric), 2) AS pp_remain,
        ROUND(CAST((COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0)) * 100.0 / NULLIF(SUM(plan), 0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM igk_stat_data
    WHERE {yc} = TRUE AND status IN ({sl})
    GROUP BY igk ORDER BY igk
    """

def _igk_stat_total_sql(yc, statuses):
    sl = "'" + "','".join(statuses) + "'"
    return f"""
    SELECT 'ИТОГО' AS igk,
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) * 100.0 / NULLIF(SUM(plan), 0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) * 100.0 / NULLIF(SUM(plan), 0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN plan END), 0) - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN fact END), 0) AS numeric), 2) AS pp_remain,
        ROUND(CAST((COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0)) * 100.0 / NULLIF(SUM(plan), 0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM igk_stat_data
    WHERE {yc} = TRUE AND status IN ({sl})
    """

def _igk_stat_response(year, statuses):
    yc = YEAR_COL.get(year)
    if not yc:
        return JsonResponse({'error': 'invalid year'}, status=400)
    with connection.cursor() as cur:
        cur.execute(_igk_stat_sql(yc, statuses))
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(_igk_stat_total_sql(yc, statuses))
        total = dict(zip(cols, cur.fetchone()))
    rows.append(total)
    return JsonResponse(rows, safe=False, json_dumps_params={'ensure_ascii': False})

def api_igk_concluded(request, year):
    return _igk_stat_response(year, CONCLUDED)

def api_igk_not_concluded(request, year):
    return _igk_stat_response(year, NOT_CONCL)

def api_igk_terminated(request, year):
    return _igk_stat_response(year, TERMINATED)


def api_day_stat_igk(request):
    today = date.today()
    prev_date = today - timedelta(days=7 if today.weekday() == 4 else 1)
    sql = """
    SELECT t.igk, t.orders_count, t.orders_sum, t.concluded_orders_count, t.concluded_orders_sum,
        t.orders_count - t.concluded_orders_count AS not_concluded_orders_count,
        ROUND(CAST(t.orders_sum - t.concluded_orders_sum AS numeric), 2) AS not_concluded_orders_sum,
        t.concluded_orders_count - COALESCE(p.concluded_orders_count, 0) AS conc_orders_delta,
        ROUND(CAST(t.concluded_orders_sum - COALESCE(p.concluded_orders_sum, 0) AS numeric), 2) AS conc_sum_delta
    FROM day_data t
    LEFT JOIN day_data p ON p.igk = t.igk AND p.cfo IS NULL AND p.upload_date = %s
    WHERE t.cfo IS NULL AND t.upload_date = %s
    """
    return _query_to_json(sql, [prev_date, today])

def api_day_stat_cfo(request):
    today = date.today()
    prev_date = today - timedelta(days=7 if today.weekday() == 4 else 1)
    sql = """
    SELECT t.igk, t.cfo, t.orders_count, t.orders_sum, t.concluded_orders_count, t.concluded_orders_sum,
        t.orders_count - t.concluded_orders_count AS not_concluded_orders_count,
        ROUND(CAST(t.orders_sum - t.concluded_orders_sum AS numeric), 2) AS not_concluded_orders_sum,
        t.concluded_orders_count - COALESCE(p.concluded_orders_count, 0) AS conc_orders_delta,
        ROUND(CAST(t.concluded_orders_sum - COALESCE(p.concluded_orders_sum, 0) AS numeric), 2) AS conc_sum_delta
    FROM day_data t
    LEFT JOIN day_data p ON p.igk = t.igk AND p.cfo = t.cfo AND p.upload_date = %s
    WHERE t.cfo IS NOT NULL AND t.upload_date = %s
    """
    return _query_to_json(sql, [prev_date, today])


def api_all_pps(request):
    sql = """
    SELECT DISTINCT igk, c_agent, cfo, contract, status,
        COALESCE(payment_type, 'ИНОЕ') AS payment_type,
        item, "order", y25, y26, y27, stage,
        ROUND(CAST(SUM(plan) OVER w_full AS numeric), 2) AS spec_sum,
        ROUND(CAST(SUM(plan) OVER w_full AS numeric), 2) AS pp_sum,
        CASE WHEN SUM(plan) OVER w_full = 0 THEN 0
             ELSE ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) OVER w_full * 100.0 / NULLIF(SUM(plan) OVER w_full, 0) AS numeric), 0)
        END AS pp_percent,
        ROUND(CAST(SUM(fact) OVER w_full AS numeric), 2) AS pp_fact,
        ROUND(CAST(SUM(fact) OVER w_order * 100.0 / NULLIF(SUM(plan) OVER w_order, 0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(SUM(plan) OVER w_order - SUM(fact) OVER w_order AS numeric), 2) AS pp_remain,
        ROUND(CAST((SUM(plan) OVER w_order - SUM(fact) OVER w_order) * 100.0 / NULLIF(SUM(plan) OVER w_order, 0) AS numeric), 0) AS remain_percent,
        pp_id, plan_date
    FROM igk_stat_data
    WINDOW
        w_full AS (PARTITION BY igk, contract, payment_type, "order", stage),
        w_order AS (PARTITION BY igk, contract, "order")
    ORDER BY igk
    """
    return _query_to_json(sql)


def api_all_contracts(request):
    search_agent = request.GET.get('agent', '').strip()
    igk_filter   = request.GET.get('igk', '').strip()
    statuses_raw = request.GET.getlist('status')
    year_filter  = request.GET.get('year', '').strip()

    conditions = ["payment_type IS NOT NULL AND TRIM(payment_type) != ''"]
    params = []

    if search_agent:
        conditions.append("c_agent ILIKE %s")
        params.append(f'%{search_agent}%')
    if igk_filter:
        conditions.append("igk LIKE %s")
        params.append(f'%{igk_filter}')
    if statuses_raw:
        placeholders = ','.join(['%s'] * len(statuses_raw))
        conditions.append(f"status IN ({placeholders})")
        params.extend(statuses_raw)
    if year_filter and year_filter in YEAR_COL:
        conditions.append(f"{YEAR_COL[year_filter]} = TRUE")

    where_clause = 'WHERE ' + ' AND '.join(conditions)

    sql_detail = f"""
        SELECT igk, c_agent, contract, status,
            COALESCE(payment_type, 'ИНОЕ') AS payment_type,
            item, "order", TRIM(stage) AS stage, y25, y26, y27,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN fact ELSE 0 END) AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact, 0)) AS numeric), 2) AS pp_remain,
            0 AS is_subtotal
        FROM igk_stat_data
        {where_clause}
        GROUP BY igk, c_agent, contract, status, payment_type, item, "order", stage, y25, y26, y27
        ORDER BY igk NULLS LAST, contract, payment_type
    """

    sql_total = f"""
        SELECT igk, c_agent, contract, status,
            'ИТОГО' AS payment_type,
            item, "order", NULL AS stage, y25, y26, y27,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN fact ELSE 0 END) AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact, 0)) AS numeric), 2) AS pp_remain,
            1 AS is_subtotal
        FROM igk_stat_data
        {where_clause}
        GROUP BY igk, c_agent, contract, status, item, "order", y25, y26, y27
        ORDER BY igk NULLS LAST, contract
    """

    with connection.cursor() as cur:
        cur.execute(sql_detail, params)
        cols = [c[0] for c in cur.description]
        detail_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(sql_total, params)
        total_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    from collections import defaultdict
    groups = defaultdict(list)
    for row in detail_rows:
        groups[(row['igk'], row['contract'], row['order'])].append(row)
    totals = {}
    for row in total_rows:
        totals[(row['igk'], row['contract'], row['order'])] = row

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


def api_history_status(request):
    sql = """
    SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
        ch.old_status, ch.new_status, isd.payment_type, isd.item,
        ROUND(CAST(SUM(isd.plan) AS numeric), 2) AS plan_sum,
        ROUND(CAST(SUM(isd.fact) AS numeric), 2) AS fact_sum,
        ch.update_date, ch.upload_date, isd.c_date
    FROM contracts_history ch
    LEFT JOIN igk_stat_data isd ON ch.hash = digest(
        concat(isd.igk, isd.c_agent, isd.contract, isd.item,
               isd."order", TRIM(isd.stage), isd.plan_date), 'md5')
    WHERE ch.old_status IS NOT NULL
    GROUP BY isd.igk, isd.c_agent, isd.cfo, isd.contract, isd.item,
             isd.payment_type, isd."order", ch.old_status, ch.new_status,
             ch.update_date, ch.upload_date, isd.c_date
    ORDER BY ch.update_date DESC NULLS LAST
    """
    return _query_to_json(sql)

def api_history_plan(request):
    sql = """
    SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
        isd.payment_type, isd.item, ch.old_plan, ch.new_plan,
        ch.plan_changed_date, isd.c_date
    FROM contracts_history ch
    LEFT JOIN igk_stat_data isd ON ch.hash = digest(
        concat(isd.igk, isd.c_agent, isd.contract, isd.item,
               isd."order", TRIM(isd.stage), isd.plan_date), 'md5')
    WHERE ch.plan_changed_date IS NOT NULL
    GROUP BY isd.igk, isd.c_agent, isd.cfo, isd.contract, isd.item,
             isd.payment_type, isd."order", ch.update_date, ch.upload_date,
             isd.c_date, ch.old_plan, ch.new_plan, ch.plan_changed_date
    ORDER BY ch.plan_changed_date DESC NULLS LAST
    """
    return _query_to_json(sql)

def api_history_fact(request):
    sql = """
    SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
        isd.payment_type, isd.item, ch.old_fact, ch.new_fact,
        ch.fact_changed_date, isd.c_date
    FROM contracts_history ch
    LEFT JOIN igk_stat_data isd ON ch.hash = digest(
        concat(isd.igk, isd.c_agent, isd.contract, isd.item,
               isd."order", TRIM(isd.stage), isd.plan_date), 'md5')
    WHERE ch.fact_changed_date IS NOT NULL
    GROUP BY isd.igk, isd.c_agent, isd.cfo, isd.contract, isd.item,
             isd.payment_type, isd."order", ch.update_date, ch.upload_date,
             isd.c_date, ch.old_fact, ch.new_fact, ch.fact_changed_date
    ORDER BY ch.fact_changed_date DESC NULLS LAST
    """
    return _query_to_json(sql)


def api_contract_dupes(request):
    sql = """
    SELECT c_agent, contract, item, "order", TRIM(stage) AS stage, plan_date, COUNT(*) AS dupes_count
    FROM igk_stat_data
    GROUP BY igk, c_agent, contract, item, "order", stage, plan_date
    HAVING COUNT(*) > 1
    ORDER BY contract, c_agent
    """
    return _query_to_json(sql)