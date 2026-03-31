CONCLUDED = ('Исполняется', 'Возвращен на уточнение', 'На согласовании', 'Подписан', 'На утверждении')
NOT_CONCL = ('Черновик',)
TERMINATED = ('Расторгнут',)
YEARS = [2025, 2026, 2027]
YEAR_COL = {str(y): f'y{str(y)[2:]}' for y in YEARS}


def _sl(statuses):
    return ', '.join(f"'{s}'" for s in statuses)


def kdr(year):
    yc = YEAR_COL.get(str(year))
    cl = _sl(CONCLUDED)
    nl = _sl(NOT_CONCL)
    return f"""
    SELECT igk,
        COUNT(DISTINCT contract) FILTER (WHERE "order" IS NOT NULL AND "order" != '') AS orders,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND "order" != ''), 0)/1e6 AS numeric), 2) AS order_sum,
        COUNT(DISTINCT contract) FILTER (WHERE "order" != '' AND status IN ({cl})) AS count_concluded,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE "order" != '' AND status IN ({cl})), 0)/1e6 AS numeric), 2) AS concluded_order_sum,
        COUNT(DISTINCT contract) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status!='Расторгнут') AS count_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS order_sum_curr_year,
        COUNT(DISTINCT contract) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status IN ({cl})) AS count_concluded_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status IN ({cl})), 0)/1e6 AS numeric), 2) AS concluded_order_sum_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS pp_sum_plan,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS pp_sum_fact,
        COUNT(DISTINCT contract) FILTER (WHERE "order" != '' AND status IN ({nl}) AND {yc}=TRUE) AS count_not_concluded_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status IN ({nl})), 0)/1e6 AS numeric), 2) AS not_concluded_order_sum_curr_year,
        CASE WHEN COUNT(DISTINCT contract) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status!='Расторгнут') = 0 THEN 0
             ELSE CAST(COUNT(DISTINCT contract) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status IN ({cl})) * 100.0
                  / NULLIF(COUNT(DISTINCT contract) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status!='Расторгнут'), 0) AS int)
        END AS count_concluded_percent_curr_year,
        CASE WHEN COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status!='Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status IN ({cl})), 0) * 100.0
                  / NULLIF(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND status!='Расторгнут'), 0) AS int)
        END AS order_sum_percent_curr_year,
        CASE WHEN COALESCE(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE(SUM(fact) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'), 0)
                  / NULLIF(SUM(plan) FILTER (WHERE "order" IS NOT NULL AND {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'), 0) * 100 AS int)
        END AS pp_percent
    FROM igk_stat_data
    GROUP BY igk ORDER BY igk
    """


def igk_stat(yc, statuses):
    sl = _sl(statuses)
    return f"""
    SELECT igk,
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс'), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс'), 0)*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс'), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс'), 0)*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс' AND plan>=0), 0)
                 - COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс' AND plan>=0), 0) AS numeric), 2) AS pp_remain,
        ROUND(CAST((COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс'), 0)
                  - COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс'), 0))*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM igk_stat_data
    WHERE {yc} = TRUE AND status IN ({sl})
    GROUP BY igk ORDER BY igk
    """


def igk_stat_total(yc, statuses):
    sl = _sl(statuses)
    return f"""
    SELECT 'ИТОГО' AS igk,
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс'), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс'), 0)*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс'), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс'), 0)*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс' AND plan>=0), 0)
                 - COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс' AND plan>=0), 0) AS numeric), 2) AS pp_remain,
        ROUND(CAST((COALESCE(SUM(plan) FILTER (WHERE payment_type='Аванс'), 0)
                  - COALESCE(SUM(fact) FILTER (WHERE payment_type='Аванс'), 0))*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM igk_stat_data
    WHERE {yc} = TRUE AND status IN ({sl})
    """


_HISTORY_JOIN = """
    FROM contracts_history ch
    LEFT JOIN igk_stat_data isd ON ch.hash = digest(
        concat(isd.igk, isd.c_agent, isd.contract, isd.item,
               isd."order", TRIM(isd.stage), isd.plan_date), 'md5')
"""

_HISTORY_GROUP = """
    isd.igk, isd.c_agent, isd.cfo, isd.contract, isd.item,
    isd.payment_type, isd."order", ch.update_date, ch.upload_date, isd.c_date
"""


def history_status():
    return f"""
        SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
            ch.old_status, ch.new_status, isd.payment_type, isd.item,
            ROUND(CAST(SUM(isd.plan) AS numeric), 2) AS plan_sum,
            ROUND(CAST(SUM(isd.fact) AS numeric), 2) AS fact_sum,
            ch.update_date, ch.upload_date, isd.c_date
        {_HISTORY_JOIN}
        WHERE ch.old_status IS NOT NULL
        GROUP BY {_HISTORY_GROUP}, ch.old_status, ch.new_status
        ORDER BY ch.update_date DESC NULLS LAST
    """


def history_plan():
    return f"""
        SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
            isd.payment_type, isd.item, ch.old_plan, ch.new_plan,
            ch.plan_changed_date, isd.c_date
        {_HISTORY_JOIN}
        WHERE ch.plan_changed_date IS NOT NULL
        GROUP BY {_HISTORY_GROUP}, ch.old_plan, ch.new_plan, ch.plan_changed_date
        ORDER BY ch.plan_changed_date DESC NULLS LAST
    """


def history_fact():
    return f"""
        SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
            isd.payment_type, isd.item, ch.old_fact, ch.new_fact,
            ch.fact_changed_date, isd.c_date
        {_HISTORY_JOIN}
        WHERE ch.fact_changed_date IS NOT NULL
        GROUP BY {_HISTORY_GROUP}, ch.old_fact, ch.new_fact, ch.fact_changed_date
        ORDER BY ch.fact_changed_date DESC NULLS LAST
    """


def contract_dupes():
    return """
        SELECT c_agent, contract, item, "order", TRIM(stage) AS stage,
               plan_date, encode(digest(concat(
               c_agent, contract, item, "order", TRIM(stage), plan_date), 'md5'), 'hex') AS hash
        FROM igk_stat_data
        GROUP BY igk, c_agent, contract, item, "order", stage, plan_date
        HAVING COUNT(*) > 1
        ORDER BY contract, c_agent
    """


def igk_detail(year, igk, statuses):
    yc = YEAR_COL.get(str(year))
    sl = _sl(statuses)
    return f"""
        SELECT contract, c_agent, status,
            COALESCE(payment_type,'ИНОЕ') AS payment_type,
            item, "order", TRIM(stage) AS stage,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS plan_sum,
            ROUND(CAST(SUM(fact) AS numeric), 2) AS fact_sum,
            ROUND(CAST(SUM(plan)-SUM(COALESCE(fact,0)) AS numeric), 2) AS remain
        FROM igk_stat_data
        WHERE igk LIKE %s AND {yc}=TRUE AND status IN ({sl})
          AND payment_type IS NOT NULL AND TRIM(payment_type) != ''
        GROUP BY contract, c_agent, status, payment_type, item, "order", stage
        ORDER BY contract, payment_type
    """


def contracts_by_agent(year):
    yc = YEAR_COL.get(str(year))
    return f"""
        SELECT igk, c_agent, contract, status, payment_type,
            item, "order", TRIM(stage) AS stage,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS plan,
            ROUND(CAST(SUM(COALESCE(fact,0)) AS numeric), 2) AS fact,
            ROUND(CAST(SUM(plan)-SUM(COALESCE(fact,0)) AS numeric), 2) AS remain
        FROM igk_stat_data
        WHERE {yc}=TRUE AND is_deleted=FALSE
          AND c_agent ILIKE %s
          AND payment_type IS NOT NULL AND TRIM(payment_type) != ''
          AND contract IS NOT NULL AND TRIM(contract) != ''
        GROUP BY igk, c_agent, contract, status, payment_type, item, "order", stage
        ORDER BY igk, contract, payment_type
    """


def all_contracts(where, params):
    detail = f"""
        SELECT igk, c_agent, contract, status,
            COALESCE(payment_type,'ИНОЕ') AS payment_type,
            item, "order", TRIM(stage) AS stage, y25, y26, y27,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(plan) FILTER (WHERE payment_type='Аванс') AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(fact) FILTER (WHERE payment_type='Аванс') AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact,0)) AS numeric), 2) AS pp_remain,
            0 AS is_subtotal
        FROM igk_stat_data {where}
        GROUP BY igk, c_agent, contract, status, payment_type, item, "order", stage, y25, y26, y27
        ORDER BY igk NULLS LAST, contract, payment_type
    """
    total = f"""
        SELECT igk, c_agent, contract, status,
            'ИТОГО' AS payment_type,
            item, "order", NULL AS stage, y25, y26, y27,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(plan) FILTER (WHERE payment_type='Аванс') AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(fact) FILTER (WHERE payment_type='Аванс') AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact,0)) AS numeric), 2) AS pp_remain,
            1 AS is_subtotal
        FROM igk_stat_data {where}
        GROUP BY igk, c_agent, contract, status, item, "order", y25, y26, y27
        ORDER BY igk NULLS LAST, contract
    """
    return detail, total, params


def advances(year):
    yc = YEAR_COL.get(str(year))
    return f"""
        SELECT MAX(igk) AS igk, MAX(c_agent) AS c_agent, MAX(cfo) AS cfo, contract,
            CASE WHEN MAX(status) IN ('Черновик','Приостановлен') THEN 'Не заключён' ELSE 'Заключён' END AS state,
            MAX(payment_type) AS payment_type, MAX(item) AS item, "order" AS qty,
            ROUND(CAST(SUM(CASE WHEN tolerance>0 THEN plan*(1+tolerance/100.0) ELSE plan END) AS numeric),2) AS spec_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type='Аванс' AND tolerance>0 THEN plan*(1+tolerance/100.0)
                              WHEN payment_type='Аванс' THEN plan ELSE 0 END) AS numeric),2) AS advance_plan,
            ROUND(CAST(SUM(CASE WHEN payment_type='Аванс' THEN COALESCE(fact,0) ELSE 0 END) AS numeric),2) AS advance_fact
        FROM igk_stat_data
        WHERE {yc}=TRUE AND is_deleted=FALSE AND status!='Расторгнут'
          AND payment_type IN ('Аванс','Постоплата')
          AND igk IS NOT NULL AND TRIM(igk)!=''
          AND cfo IS NOT NULL AND TRIM(cfo)!=''
          AND contract IS NOT NULL AND TRIM(contract)!=''
        GROUP BY contract, "order"
        ORDER BY MAX(igk), MAX(cfo), contract, "order"
    """


def kdr_export(year):
    yc = YEAR_COL.get(str(year))
    cl = _sl(CONCLUDED)
    nl = _sl(NOT_CONCL)
    return f"""
        SELECT MAX(igk) AS igk, cfo,
            COUNT(DISTINCT contract) AS total_count,
            ROUND(CAST(COALESCE(SUM(plan),0)/1e6 AS numeric),2) AS total_sum,
            COUNT(DISTINCT contract) FILTER (WHERE status IN ({cl})) AS concl_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE status IN ({cl})),0)/1e6 AS numeric),2) AS concl_sum,
            COUNT(DISTINCT contract) FILTER (WHERE {yc}=TRUE AND status!='Расторгнут') AS year_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc}=TRUE AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS year_sum,
            COUNT(DISTINCT contract) FILTER (WHERE {yc}=TRUE AND status IN ({cl})) AS year_concl_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc}=TRUE AND status IN ({cl})),0)/1e6 AS numeric),2) AS year_concl_sum,
            COUNT(DISTINCT contract) FILTER (WHERE {yc}=TRUE AND status IN ({nl})) AS year_not_concl_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc}=TRUE AND status IN ({nl})),0)/1e6 AS numeric),2) AS year_not_concl_sum,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS pp_plan,
            ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE {yc}=TRUE AND payment_type='Аванс' AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS pp_fact,
            0 AS delta_concl_count
        FROM igk_stat_data
        WHERE igk IS NOT NULL AND TRIM(igk)!='' AND cfo IS NOT NULL AND TRIM(cfo)!=''
        GROUP BY RIGHT(igk,4), cfo
        ORDER BY RIGHT(igk,4), cfo
    """


def kdr_delta(yc, start_date, end_date):
    return """
        SELECT s_end.igk, s_end.cfo,
            COALESCE(s_end.cnt, 0) - COALESCE(s_start.cnt, 0) AS delta
        FROM (
            SELECT igk, cfo, concluded_count AS cnt
            FROM contract_counts_snapshot
            WHERE year_col = %s AND upload_date <= %s
            ORDER BY upload_date DESC
        ) s_end
        LEFT JOIN (
            SELECT igk, cfo, concluded_count AS cnt
            FROM contract_counts_snapshot
            WHERE year_col = %s AND upload_date < %s
            ORDER BY upload_date DESC
        ) s_start ON s_end.igk = s_start.igk AND s_end.cfo = s_start.cfo
    """, [yc, end_date, yc, start_date]


def export_contracts_by_agent(year, conditions, params):
    yc = YEAR_COL.get(str(year))
    where = 'WHERE ' + ' AND '.join(conditions)
    return f"""
        SELECT igk, c_agent, cfo, contract, status, payment_type, item,
               "order", TRIM(stage) AS stage,
               ROUND(CAST(SUM(plan) AS numeric),2) AS plan,
               ROUND(CAST(SUM(COALESCE(fact,0)) AS numeric),2) AS fact,
               ROUND(CAST(SUM(plan)-SUM(COALESCE(fact,0)) AS numeric),2) AS remain
        FROM igk_stat_data
        WHERE {' AND '.join(conditions)}
        GROUP BY igk, c_agent, cfo, contract, status, payment_type, item, "order", stage
        ORDER BY igk, c_agent, contract, "order", payment_type
    """, params


def distinct_igk_suffixes():
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM igk_stat_data
        WHERE igk IS NOT NULL ORDER BY RIGHT(igk, 4)
    """


def distinct_agents():
    return """
        SELECT DISTINCT c_agent FROM igk_stat_data
        WHERE c_agent IS NOT NULL AND TRIM(c_agent) != ''
        ORDER BY c_agent
    """