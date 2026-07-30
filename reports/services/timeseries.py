from .queries import CONCLUDED, NOT_CONCL

AGE_BUCKETS = (
    ("overdue_12", "Просрочено более года"),
    ("overdue_6", "Просрочено 6-12 месяцев"),
    ("overdue_3", "Просрочено 3-6 месяцев"),
    ("overdue_0", "Просрочено до 3 месяцев"),
    ("ahead", "Срок ещё не наступил"),
)


def contracts_backlog(year_col, igk):
    not_concl = ", ".join(["%s"] * len(NOT_CONCL))
    sql = f"""
        WITH src AS (
            SELECT plan,
                   to_date(plan_date, 'YYYY.MM') AS due
            FROM igk_stat_data
            WHERE {year_col} = TRUE
              AND igk = %s
              AND status IN ({not_concl})
              AND plan_date IS NOT NULL AND TRIM(plan_date) <> ''
        )
        SELECT CASE
                   WHEN due >= date_trunc('month', CURRENT_DATE) THEN 'ahead'
                   WHEN due >= CURRENT_DATE - INTERVAL '3 months' THEN 'overdue_0'
                   WHEN due >= CURRENT_DATE - INTERVAL '6 months' THEN 'overdue_3'
                   WHEN due >= CURRENT_DATE - INTERVAL '12 months' THEN 'overdue_6'
                   ELSE 'overdue_12'
               END AS bucket,
               COUNT(*) AS cnt,
               COALESCE(SUM(plan), 0) AS plan_sum
        FROM src
        GROUP BY 1
    """
    return sql, [igk, *NOT_CONCL]


def znp_monthly(year_col, igk):
    concluded = ", ".join(["%s"] * len(CONCLUDED))
    sql = f"""
        SELECT ym,
               COALESCE(SUM(plan_sum), 0) AS plan_sum,
               COALESCE(SUM(fact_sum), 0) AS fact_sum
        FROM (
            SELECT to_char(z.plan_payment_date, 'YYYY.MM') AS ym,
                   z.plan_sum AS plan_sum, 0 AS fact_sum
            FROM znp_data z
            JOIN igk_stat_data i ON i.pp_id = z.parent_id
            WHERE i.igk = %s AND i.status IN ({concluded}) AND i.{year_col} = TRUE
              AND z.plan_payment_date IS NOT NULL
            UNION ALL
            SELECT to_char(z.fact_payment_date, 'YYYY.MM') AS ym,
                   0 AS plan_sum, z.fact_sum AS fact_sum
            FROM znp_data z
            JOIN igk_stat_data i ON i.pp_id = z.parent_id
            WHERE i.igk = %s AND i.status IN ({concluded}) AND i.{year_col} = TRUE
              AND z.fact_payment_date IS NOT NULL
        ) t
        GROUP BY ym
        ORDER BY ym
    """
    return sql, [igk, *CONCLUDED, igk, *CONCLUDED]


SAP_STAGE_COLUMNS = ("stage_e", "stage_f", "payment_possible")


def znp_sap_monthly(igk):
    allowed_cfo = [str(n) for n in range(420, 430)]
    cfo_ph = ", ".join(["%s"] * len(allowed_cfo))
    igk_filter = "AND igk = %s" if igk else ""

    parts = []
    params = []
    for column in SAP_STAGE_COLUMNS:
        parts.append(f"""
            SELECT to_char({column}, 'YYYY.MM') AS ym, '{column}' AS stage,
                   1 AS cnt, COALESCE(vv_sum, 0) AS amount
            FROM znp_data_sap
            WHERE {column} IS NOT NULL
              AND cfo IN ({cfo_ph})
              {igk_filter}
            """)
        params.extend(allowed_cfo)
        if igk:
            params.append(igk)

    sql = f"""
        SELECT ym, stage, SUM(cnt) AS cnt, SUM(amount) AS amount
        FROM ({" UNION ALL ".join(parts)}) t
        GROUP BY ym, stage
        ORDER BY ym
    """
    return sql, params
