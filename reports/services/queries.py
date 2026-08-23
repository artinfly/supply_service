from datetime import datetime

from django.utils import timezone

CONCLUDED = (
    "Исполняется",
    "Возвращен на уточнение",
    "На согласовании",
    "Подписан",
    "На утверждении",
    "Исполнен",
)
NOT_CONCL = ("Черновик",)
ADVANCE = "Аванс"
ZNP_APPROVED = "Утвержден"
POSTPAYMENT = "Постоплата"
TERMINATED = ("Расторгнут",)
YEARS = [2025, 2026, 2027]
YEAR_COL = {str(y): f"y{str(y)[2:]}" for y in YEARS}

HAS_ORDER = '"order" IS NOT NULL AND TRIM("order") != \'\''

SAP_CFO = tuple(str(n) for n in range(420, 430))


def valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def valid_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = timezone.localdate().year
    return year if year in YEARS else YEARS[-1]


def needs_znp(alias="i"):
    p = f"{alias}." if alias else ""
    return (
        f"COALESCE({p}remainder, 0) > "
        f"GREATEST(COALESCE({p}tolerance, 0) * COALESCE({p}contract_sum, 0) / 100.0, 0)"
    )


def _sl(statuses):
    return ", ".join(f"'{s}'" for s in statuses)


def escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def kdr(year):
    yc = YEAR_COL.get(str(year))
    cl = _sl(CONCLUDED)
    nl = _sl(NOT_CONCL)
    return f"""
    SELECT igk,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER}) AS orders,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER}), 0)/1e6 AS numeric), 2) AS order_sum,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND status IN ({cl})) AS count_concluded,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND status IN ({cl})), 0)/1e6 AS numeric), 2) AS concluded_order_sum,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status!='Расторгнут') AS count_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS order_sum_curr_year,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status IN ({cl})) AS count_concluded_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status IN ({cl})), 0)/1e6 AS numeric), 2) AS concluded_order_sum_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS pp_sum_plan,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS pp_sum_fact,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND status IN ({nl}) AND {yc}=TRUE) AS count_not_concluded_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status IN ({nl})), 0)/1e6 AS numeric), 2) AS not_concluded_order_sum_curr_year,
        CASE WHEN COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status!='Расторгнут') = 0 THEN 0
             ELSE CAST(COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status IN ({cl})) * 100.0
                  / NULLIF(COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status!='Расторгнут'), 0) AS int)
        END AS count_concluded_percent_curr_year,
        CASE WHEN COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status!='Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status IN ({cl})), 0) * 100.0
                  / NULLIF(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND status!='Расторгнут'), 0) AS int)
        END AS order_sum_percent_curr_year,
        CASE WHEN COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE(SUM(fact) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0)
                  / NULLIF(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0) * 100 AS int)
        END AS pp_percent
    FROM igk_stat_data
    GROUP BY igk ORDER BY igk
    """


_IGK_STAT_COLS = f"""
        ROUND(CAST(COALESCE(SUM(plan), 0) AS numeric), 2) AS spec_sum,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}'), 0) AS numeric), 2) AS pp_sum,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}'), 0)*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS pp_percent,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}'), 0) AS numeric), 2) AS pp_fact,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}'), 0)*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS fact_percent,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}' AND plan>=0), 0)
                 - COALESCE(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}' AND plan>=0), 0) AS numeric), 2) AS pp_remain,
        ROUND(CAST((COALESCE(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}'), 0)
                  - COALESCE(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}'), 0))*100.0 / NULLIF(SUM(plan),0) AS numeric), 0) AS remain_percent,
        COUNT(*) AS pp_quantity
    FROM igk_stat_data
    WHERE {{yc}} = TRUE AND status IN ({{sl}})
"""


def igk_stat(yc, statuses):
    body = _IGK_STAT_COLS.format(yc=yc, sl=_sl(statuses))
    return f"""
    SELECT igk,{body}
    GROUP BY igk ORDER BY igk
    """


def igk_stat_total(yc, statuses):
    body = _IGK_STAT_COLS.format(yc=yc, sl=_sl(statuses))
    return f"""
    SELECT 'ИТОГО' AS igk,{body}
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
            ROUND(CAST(ch.old_plan * 100.0
                  / NULLIF(ch.old_contract_sum, 0) AS numeric), 2) AS old_percent,
            ROUND(CAST(ch.new_plan * 100.0
                  / NULLIF(ch.new_contract_sum, 0) AS numeric), 2) AS new_percent,
            ch.plan_changed_date, isd.c_date
        {_HISTORY_JOIN}
        WHERE ch.plan_changed_date IS NOT NULL
        GROUP BY {_HISTORY_GROUP}, ch.old_plan, ch.new_plan, ch.plan_changed_date,
                 ch.old_contract_sum, ch.new_contract_sum
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


def dupes_filter(cfo, year):
    conditions = []
    params = []
    if cfo:
        conditions.append("TRIM(cfo) = %s")
        params.append(cfo)
    if year in YEAR_COL:
        conditions.append(f"{YEAR_COL[year]} = TRUE")
    return conditions, params


def contract_dupes(cfo=None, year=None):
    conditions, params = dupes_filter(cfo, year)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT RIGHT(igk, 4) AS igk,
               STRING_AGG(DISTINCT TRIM(cfo), ', ') AS cfo, c_agent, contract, item, "order",
               TRIM(stage) AS stage, plan_date,
               encode(digest(concat(
               igk, c_agent, contract, item, "order", TRIM(stage), plan_date),
               'md5'), 'hex') AS hash
        FROM igk_stat_data
        {where}
        GROUP BY igk, c_agent, contract, item, "order", TRIM(stage), plan_date
        HAVING COUNT(*) > 1
        ORDER BY contract, c_agent
    """
    return sql, params


def contract_dupes_by_order(cfo=None, year=None):
    conditions, params = dupes_filter(cfo, year)
    extra = ("AND " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT RIGHT(igk, 4) AS igk,
               STRING_AGG(DISTINCT TRIM(cfo), ', ') AS cfo, item, "order",
               COUNT(*) AS rows_count,
               COUNT(DISTINCT contract) AS contracts_count,
               COUNT(DISTINCT c_agent) AS agents_count,
               ROUND(CAST(SUM(plan) AS numeric), 2) AS plan_sum
        FROM igk_stat_data
        WHERE igk IS NOT NULL AND TRIM(igk) != ''
          AND item IS NOT NULL AND TRIM(item) != ''
          AND {HAS_ORDER}
          {extra}
        GROUP BY RIGHT(igk, 4), item, "order"
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, igk, item
    """
    return sql, params


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


def all_contracts(where):
    detail = f"""
        SELECT igk, c_agent, contract, status,
            COALESCE(payment_type,'ИНОЕ') AS payment_type,
            item, "order", TRIM(stage) AS stage, y25, y26, y27,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_fact,
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
            ROUND(CAST(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact,0)) AS numeric), 2) AS pp_remain,
            1 AS is_subtotal
        FROM igk_stat_data {where}
        GROUP BY igk, c_agent, contract, status, item, "order", y25, y26, y27
        ORDER BY igk NULLS LAST, contract
    """
    return detail, total


def advances(year):
    yc = YEAR_COL.get(str(year))
    return f"""
        SELECT MAX(igk) AS igk, MAX(c_agent) AS c_agent, MAX(cfo) AS cfo, contract,
            CASE WHEN MAX(status) IN ('Черновик','Приостановлен') THEN 'Не заключён' ELSE 'Заключён' END AS state,
            MAX(payment_type) AS payment_type, MAX(item) AS item, "order" AS qty,
            ROUND(CAST(SUM(CASE WHEN tolerance>0 THEN plan*(1+tolerance/100.0) ELSE plan END) AS numeric),2) AS spec_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type='{ADVANCE}' AND tolerance>0 THEN plan*(1+tolerance/100.0)
                              WHEN payment_type='{ADVANCE}' THEN plan ELSE 0 END) AS numeric),2) AS advance_plan,
            ROUND(CAST(SUM(CASE WHEN payment_type='{ADVANCE}' THEN COALESCE(fact,0) ELSE 0 END) AS numeric),2) AS advance_fact
        FROM igk_stat_data
        WHERE {yc}=TRUE AND status!='Расторгнут'
          AND payment_type IN ('{ADVANCE}','{POSTPAYMENT}')
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
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS pp_plan,
            ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE {yc}=TRUE AND payment_type='{ADVANCE}' AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS pp_fact,
            0 AS delta_concl_count
        FROM igk_stat_data
        WHERE igk IS NOT NULL AND TRIM(igk)!='' AND cfo IS NOT NULL AND TRIM(cfo)!=''
        GROUP BY RIGHT(igk,4), cfo
        ORDER BY igk, cfo
    """


def kdr_delta(yc, start_date, end_date):
    return """
        with data_t1 as (
            select igk, cfo, concluded_count as count_t1
            from contract_counts_snapshot ccs
            where upload_date = %s and year_col = %s
        ),
        data_t2 as (
            select igk, cfo, concluded_count as count_t2
            from contract_counts_snapshot ccs
            where upload_date = %s and year_col = %s
        )
        select
            coalesce(t1.igk, t2.igk) as igk,
            coalesce(t1.cfo, t2.cfo) as cfo,
            greatest(0, coalesce(t2.count_t2, 0) - coalesce(t1.count_t1, 0)) as delta
        from data_t1 t1
        full outer join data_t2 t2 using(igk, cfo)
    """, [
        start_date,
        yc,
        end_date,
        yc,
    ]


def contracts_by_agent_filter(yc, agent):
    conditions = [
        f"{yc}=TRUE",
        "contract IS NOT NULL AND TRIM(contract)!=''",
        "payment_type IS NOT NULL AND TRIM(payment_type)!=''",
    ]
    params = []
    if agent:
        conditions.append("c_agent ILIKE %s")
        params.append(f"%{escape_like(agent)}%")
    return conditions, params


def export_contracts_by_agent(conditions):
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
    """


def distinct_igk_suffixes():
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM igk_stat_data
        WHERE igk IS NOT NULL ORDER BY RIGHT(igk, 4)
    """


def distinct_cfo():
    return """
        SELECT DISTINCT cfo FROM igk_stat_data
        WHERE cfo IS NOT NULL AND TRIM(cfo) != ''
        ORDER BY cfo
    """


def distinct_sap_igk():
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM znp_data_sap
        WHERE igk IS NOT NULL AND TRIM(igk) != ''
        ORDER BY 1
    """


def distinct_sap_cfo():
    return f"""
        SELECT DISTINCT cfo FROM znp_data_sap
        WHERE cfo IN ({_sl(SAP_CFO)})
        ORDER BY cfo
    """


def distinct_agents():
    return """
        SELECT DISTINCT c_agent FROM igk_stat_data
        WHERE c_agent IS NOT NULL AND TRIM(c_agent) != ''
        ORDER BY c_agent
    """


def znp_list(where):
    return f"""
        SELECT
            i.pp_id, i.igk, i.contract, i.c_agent, i.cfo, i.payment_type,
            i.plan AS position_sum,
            z.id AS znp_id, z.plan_doc, z.payment_purpose,
            z.plan_payment_date, z.fact_payment_date,
            z.plan_sum AS znp_plan_sum, z.fact_sum AS znp_fact_sum,
            z.znp_igk,
            CASE
                WHEN z.id IS NOT NULL AND z.znp_status IS DISTINCT FROM '{ZNP_APPROVED}' THEN 'На оформлении ЗнП'
                WHEN z.id IS NULL AND i.payment_type = '{ADVANCE}'
                    THEN 'Не оформлено (Аванс)'
                WHEN z.id IS NULL AND i.payment_type = '{POSTPAYMENT}'
                    THEN 'Не оформлено (Постоплата)'
                WHEN z.id IS NULL THEN 'Не оформлено ЗнП'
                WHEN i.payment_type = '{ADVANCE}' AND z.fact_sum IS NOT NULL THEN 'Оплачено ЗнП (Аванс)'
                WHEN i.payment_type = '{ADVANCE}' THEN 'Оформлено ЗнП (Аванс)'
                WHEN i.payment_type = '{POSTPAYMENT}' AND z.fact_sum IS NOT NULL THEN 'Оплачено ЗнП (Постоплата)'
                WHEN i.payment_type = '{POSTPAYMENT}' THEN 'Оформлено ЗнП (Постоплата)'
                ELSE 'Оформлено ЗнП (иное)'
            END AS znp_status
        FROM igk_stat_data i
        LEFT JOIN znp_data z ON z.parent_id = i.pp_id
        {where}
        ORDER BY i.contract, z.plan_payment_date NULLS LAST
    """


def contracts_appeared(kind):
    return """
        SELECT upload_date, reason, RIGHT(igk, 4) AS igk, cfo, c_agent, contract, item, order_num, stage, plan_date, status, plan, contract_sum
        FROM contracts_appeared
        WHERE kind = %s
        ORDER BY upload_date DESC, igk, contract, item
    """, [
        kind
    ]
