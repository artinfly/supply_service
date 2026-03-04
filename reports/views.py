from django.http import JsonResponse
from django.shortcuts import render
from django.db import connection
from datetime import date, timedelta


# ──────────────────────────────────────────────────────────────────────
# Точные статусы из Excel
# ──────────────────────────────────────────────────────────────────────
CONCLUDED  = ('Заключен', 'Исполнен', 'Исполняется')
NOT_CONCL  = ('Не заключен',)
TERMINATED = ('Расторгнут',)
ADVANCE    = 'Аванс'


# ──────────────────────────────────────────────────────────────────────
# HTML-страницы (просто рендерят шаблон, данные грузит JS через API)
# ──────────────────────────────────────────────────────────────────────

def index(request):
    return render(request, 'reports/index.html')

def kdr_table(request, year):
    return render(request, 'reports/kdr_table.html', {'year': year})

def igk_concluded_table(request, year):
    return render(request, 'reports/igk_table.html', {
        'year': year, 'report_type': 'concluded', 'title': f'Заключённые ИГК {year}'
    })

def igk_not_concluded_table(request, year):
    return render(request, 'reports/igk_table.html', {
        'year': year, 'report_type': 'not_concluded', 'title': f'Незаключённые ИГК {year}'
    })

def igk_terminated_table(request, year):
    return render(request, 'reports/igk_table.html', {
        'year': year, 'report_type': 'terminated', 'title': f'Расторгнутые ИГК {year}'
    })

def day_stat_only_igk_table(request):
    return render(request, 'reports/day_stat_only_igk.html')

def day_stat_with_cfo_table(request):
    return render(request, 'reports/day_stat_with_cfo.html')

def all_pps_table(request):
    return render(request, 'reports/all_pps.html')

def all_contracts_table(request):
    return render(request, 'reports/all_contracts.html')


# ──────────────────────────────────────────────────────────────────────
# Вспомогательная функция: выполнить SQL и вернуть JsonResponse
# ──────────────────────────────────────────────────────────────────────

def _query_to_json(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    data = []
    for row in rows:
        record = {}
        for col, val in zip(cols, row):
            # Decimal → float для сериализации
            if hasattr(val, '__float__'):
                val = float(val)
            record[col] = val
        data.append(record)
    return JsonResponse(data, safe=False,
                        json_dumps_params={'ensure_ascii': False})


# ──────────────────────────────────────────────────────────────────────
# API: KDR_Stat
# ──────────────────────────────────────────────────────────────────────

def api_kdr(request, year):
    year_col = {'2025': 'y25', '2026': 'y26', '2027': 'y27'}.get(year)
    if not year_col:
        return JsonResponse({'error': 'Неверный год'}, status=400)

    sql = f"""
    SELECT
        igk,
        (SELECT COUNT(DISTINCT contract)
         FROM dbo.igk_stat_data p2
         WHERE p2.igk = p.igk AND "order" IS NOT NULL AND "order" != '') AS orders,

        ROUND(CAST(
            (SELECT COALESCE(SUM(plan), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL AND "order" != '')
            / 1000000.0 AS numeric), 2) AS order_sum,

        (SELECT COUNT(DISTINCT contract)
         FROM dbo.igk_stat_data
         WHERE igk = p.igk AND "order" != ''
           AND status IN ('Заключен','Исполнен','Исполняется')) AS count_concluded,

        ROUND(CAST(
            (SELECT COALESCE(SUM(plan), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" != ''
               AND status IN ('Заключен','Исполнен','Исполняется'))
            / 1000000.0 AS numeric), 2) AS concluded_order_sum,

        (SELECT COUNT(DISTINCT contract)
         FROM dbo.igk_stat_data
         WHERE igk = p.igk AND "order" IS NOT NULL
           AND {year_col} = TRUE AND status != 'Расторгнут') AS count_curr_year,

        ROUND(CAST(
            (SELECT COALESCE(SUM(plan), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL
               AND {year_col} = TRUE AND status != 'Расторгнут')
            / 1000000.0 AS numeric), 2) AS order_sum_curr_year,

        (SELECT COUNT(DISTINCT contract)
         FROM dbo.igk_stat_data
         WHERE igk = p.igk AND "order" IS NOT NULL
           AND {year_col} = TRUE
           AND status IN ('Заключен','Исполнен','Исполняется')) AS count_concluded_curr_year,

        ROUND(CAST(
            (SELECT COALESCE(SUM(plan), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL
               AND {year_col} = TRUE
               AND status IN ('Заключен','Исполнен','Исполняется'))
            / 1000000.0 AS numeric), 2) AS concluded_order_sum_curr_year,

        ROUND(CAST(
            (SELECT COALESCE(SUM(plan), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL
               AND {year_col} = TRUE AND payment_type = 'Аванс'
               AND status != 'Расторгнут')
            / 1000000.0 AS numeric), 2) AS pp_sum_plan,

        ROUND(CAST(
            (SELECT COALESCE(SUM(fact), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL
               AND {year_col} = TRUE AND payment_type = 'Аванс'
               AND status != 'Расторгнут')
            / 1000000.0 AS numeric), 2) AS pp_sum_fact,

        (SELECT COUNT(DISTINCT contract)
         FROM dbo.igk_stat_data
         WHERE igk = p.igk AND "order" != ''
           AND status = 'Не заключен'
           AND {year_col} = TRUE) AS count_not_concluded_curr_year,

        ROUND(CAST(
            (SELECT COALESCE(SUM(plan), 0)
             FROM dbo.igk_stat_data
             WHERE igk = p.igk AND "order" IS NOT NULL
               AND {year_col} = TRUE AND status = 'Не заключен')
            / 1000000.0 AS numeric), 2) AS not_concluded_order_sum_curr_year,

        CASE
            WHEN (SELECT COUNT(DISTINCT contract) FROM dbo.igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL
                    AND {year_col} = TRUE AND status != 'Расторгнут') = 0 THEN 0
            ELSE CAST(
                (SELECT COUNT(DISTINCT contract) FROM dbo.igk_stat_data
                 WHERE igk = p.igk AND "order" IS NOT NULL
                   AND {year_col} = TRUE
                   AND status IN ('Заключен','Исполнен','Исполняется')) * 100.0
                /
                (SELECT COUNT(DISTINCT contract) FROM dbo.igk_stat_data
                 WHERE igk = p.igk AND "order" IS NOT NULL
                   AND {year_col} = TRUE AND status != 'Расторгнут')
            AS int)
        END AS count_concluded_percent_curr_year,

        CASE
            WHEN (SELECT SUM(plan) FROM dbo.igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL
                    AND {year_col} = TRUE AND status != 'Расторгнут') IS NULL THEN 0
            ELSE CAST(
                (SELECT COALESCE(SUM(plan), 0) FROM dbo.igk_stat_data
                 WHERE igk = p.igk AND "order" IS NOT NULL
                   AND {year_col} = TRUE
                   AND status IN ('Заключен','Исполнен','Исполняется')) * 100.0
                /
                NULLIF((SELECT SUM(plan) FROM dbo.igk_stat_data
                        WHERE igk = p.igk AND "order" IS NOT NULL
                          AND {year_col} = TRUE AND status != 'Расторгнут'), 0)
            AS int)
        END AS order_sum_percent_curr_year,

        CASE
            WHEN (SELECT SUM(plan) FROM dbo.igk_stat_data
                  WHERE igk = p.igk AND "order" IS NOT NULL
                    AND {year_col} = TRUE AND payment_type = 'Аванс'
                    AND status != 'Расторгнут') IS NULL THEN 0
            ELSE CAST(
                (SELECT COALESCE(SUM(fact), 0) FROM dbo.igk_stat_data
                 WHERE igk = p.igk AND "order" IS NOT NULL
                   AND {year_col} = TRUE AND payment_type = 'Аванс'
                   AND status != 'Расторгнут')
                /
                NULLIF((SELECT SUM(plan) FROM dbo.igk_stat_data
                        WHERE igk = p.igk AND "order" IS NOT NULL
                          AND {year_col} = TRUE AND payment_type = 'Аванс'
                          AND status != 'Расторгнут'), 0) * 100
            AS int)
        END AS pp_percent

    FROM dbo.igk_stat_data p
    GROUP BY igk
    ORDER BY igk
    """
    return _query_to_json(sql)


# ──────────────────────────────────────────────────────────────────────
# API: IGK_Stat (Заключённые / Незаключённые / Расторгнутые)
# ──────────────────────────────────────────────────────────────────────

def _igk_stat_sql(year_col, statuses):
    status_list = "'" + "','".join(statuses) + "'"
    return f"""
    SELECT
        igk,
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(
            COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) * 100.0
            / NULLIF(SUM(plan), 0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(
            COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) * 100.0
            / NULLIF(SUM(plan), 0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(
            COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN plan END), 0)
            - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN fact END), 0)
        AS numeric), 2) AS pp_remain,
        ROUND(CAST(
            (COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0)
             - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0)) * 100.0
            / NULLIF(SUM(plan), 0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM dbo.igk_stat_data
    WHERE {year_col} = TRUE AND status IN ({status_list})
    GROUP BY igk
    ORDER BY igk
    """

def _igk_stat_total_sql(year_col, statuses):
    status_list = "'" + "','".join(statuses) + "'"
    return f"""
    SELECT
        'ИТОГО' AS igk,
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(
            COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0) * 100.0
            / NULLIF(SUM(plan), 0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(
            COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0) * 100.0
            / NULLIF(SUM(plan), 0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(
            COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN plan END), 0)
            - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' AND plan >= 0 THEN fact END), 0)
        AS numeric), 2) AS pp_remain,
        ROUND(CAST(
            (COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN plan END), 0)
             - COALESCE(SUM(CASE WHEN payment_type = 'Аванс' THEN fact END), 0)) * 100.0
            / NULLIF(SUM(plan), 0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM dbo.igk_stat_data
    WHERE {year_col} = TRUE AND status IN ({status_list})
    """

def _igk_stat_response(year, statuses):
    year_col = {'2025': 'y25', '2026': 'y26', '2027': 'y27'}.get(year)
    if not year_col:
        return JsonResponse({'error': 'Неверный год'}, status=400)

    with connection.cursor() as cur:
        cur.execute(_igk_stat_sql(year_col, statuses))
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        cur.execute(_igk_stat_total_sql(year_col, statuses))
        total_cols = [c[0] for c in cur.description]
        total = dict(zip(total_cols, cur.fetchone()))

    rows.append(total)
    return JsonResponse(rows, safe=False,
                        json_dumps_params={'ensure_ascii': False})

def api_igk_concluded(request, year):
    return _igk_stat_response(year, CONCLUDED)

def api_igk_not_concluded(request, year):
    return _igk_stat_response(year, NOT_CONCL)

def api_igk_terminated(request, year):
    return _igk_stat_response(year, TERMINATED)


# ──────────────────────────────────────────────────────────────────────
# API: Day Stat
# ──────────────────────────────────────────────────────────────────────

def api_day_stat_igk(request):
    today = date.today()
    is_friday = today.weekday() == 4
    prev_date = today - timedelta(days=7 if is_friday else 1)

    sql = """
    SELECT
        t.igk,
        t.orders_count,
        t.orders_sum,
        t.concluded_orders_count,
        t.concluded_orders_sum,
        t.orders_count - t.concluded_orders_count AS not_concluded_orders_count,
        ROUND(CAST(t.orders_sum - t.concluded_orders_sum AS numeric), 2) AS not_concluded_orders_sum,
        t.concluded_orders_count - COALESCE(p.concluded_orders_count, 0) AS conc_orders_delta,
        ROUND(CAST(t.concluded_orders_sum - COALESCE(p.concluded_orders_sum, 0) AS numeric), 2) AS conc_sum_delta
    FROM dbo.day_data t
    LEFT JOIN dbo.day_data p
        ON p.igk = t.igk AND p.cfo IS NULL AND p.upload_date = %s
    WHERE t.cfo IS NULL AND t.upload_date = %s
    """
    return _query_to_json(sql, [prev_date, today])

def api_day_stat_cfo(request):
    today = date.today()
    is_friday = today.weekday() == 4
    prev_date = today - timedelta(days=7 if is_friday else 1)

    sql = """
    SELECT
        t.igk,
        t.cfo,
        t.orders_count,
        t.orders_sum,
        t.concluded_orders_count,
        t.concluded_orders_sum,
        t.orders_count - t.concluded_orders_count AS not_concluded_orders_count,
        ROUND(CAST(t.orders_sum - t.concluded_orders_sum AS numeric), 2) AS not_concluded_orders_sum,
        t.concluded_orders_count - COALESCE(p.concluded_orders_count, 0) AS conc_orders_delta,
        ROUND(CAST(t.concluded_orders_sum - COALESCE(p.concluded_orders_sum, 0) AS numeric), 2) AS conc_sum_delta
    FROM dbo.day_data t
    LEFT JOIN dbo.day_data p
        ON p.igk = t.igk AND p.cfo = t.cfo AND p.upload_date = %s
    WHERE t.cfo IS NOT NULL AND t.upload_date = %s
    """
    return _query_to_json(sql, [prev_date, today])


# ──────────────────────────────────────────────────────────────────────
# API: AllPPs
# ──────────────────────────────────────────────────────────────────────

def api_all_pps(request):
    sql = """
    SELECT DISTINCT
        igk, c_agent, cfo, contract, status,
        COALESCE(payment_type, 'ИНОЕ') AS payment_type,
        item, "order", y25, y26, y27, stage,
        ROUND(CAST(SUM(plan) OVER w_full AS numeric), 2) AS spec_sum,
        ROUND(CAST(SUM(plan) OVER w_full AS numeric), 2) AS pp_sum,
        CASE
            WHEN SUM(plan) OVER w_full = 0 THEN 0
            ELSE ROUND(CAST(
                SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) OVER w_full
                * 100.0 / NULLIF(SUM(plan) OVER w_full, 0) AS numeric), 0)
        END AS pp_percent,
        ROUND(CAST(SUM(fact) OVER w_full AS numeric), 2) AS pp_fact,
        ROUND(CAST(SUM(fact) OVER w_order * 100.0
              / NULLIF(SUM(plan) OVER w_order, 0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(SUM(plan) OVER w_order - SUM(fact) OVER w_order AS numeric), 2) AS pp_remain,
        ROUND(CAST(
            (SUM(plan) OVER w_order - SUM(fact) OVER w_order) * 100.0
            / NULLIF(SUM(plan) OVER w_order, 0) AS numeric), 0) AS remain_percent,
        pp_id,
        plan_date
    FROM dbo.igk_stat_data
    WINDOW
        w_full  AS (PARTITION BY igk, contract, payment_type, "order", stage),
        w_order AS (PARTITION BY igk, contract, "order")
    ORDER BY igk
    """
    return _query_to_json(sql)


# ──────────────────────────────────────────────────────────────────────
# API: AllContracts
# ──────────────────────────────────────────────────────────────────────

def api_all_contracts(request):
    sql = """
    SELECT
        igk, c_agent, contract, status,
        COALESCE(payment_type, 'ИНОЕ') AS payment_type,
        item, "order", stage, y25, y26, y27,
        ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
        ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) AS numeric), 2) AS pp_sum,
        ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN fact ELSE 0 END) AS numeric), 2) AS pp_fact,
        ROUND(CAST(SUM(plan) - SUM(COALESCE(fact, 0)) AS numeric), 2) AS pp_remain
    FROM dbo.igk_stat_data
    GROUP BY GROUPING SETS (
        (igk, c_agent, contract, payment_type, item, "order", stage, y25, y26, y27, status),
        (c_agent, contract, igk, "order", y25, y26, y27, item, status)
    )
    ORDER BY igk NULLS LAST, contract
    """
    return _query_to_json(sql)