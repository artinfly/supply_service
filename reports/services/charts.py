from .queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    POSTPAYMENT,
    ZNP_PENDING,
)

CONTRACT_AGE = (
    ("overdue_12", "Просрочено более года"),
    ("overdue_6", "Просрочено 6-12 месяцев"),
    ("overdue_0", "Просрочено до 6 месяцев"),
    ("ahead", "Срок ещё не наступил"),
)

ZNP_STAGES = (
    ("not_issued", "Не оформлено"),
    ("in_progress", "На оформлении"),
    ("issued", "Оформлено"),
    ("paid", "Оплачено"),
)

SAP_STAGES = (
    ("waiting", "На согласовании"),
    ("sent", "Передано в 18 отдел"),
    ("confirmed", "Подтверждено 18 отделом"),
    ("paid", "Оплачено"),
)


def contracts_by_cfo(year_col, igk):
    not_concl = ", ".join(["%s"] * len(NOT_CONCL))
    sql = f"""
        SELECT cfo,
               CASE
                   WHEN due >= date_trunc('month', CURRENT_DATE) THEN 'ahead'
                   WHEN due >= CURRENT_DATE - INTERVAL '6 months' THEN 'overdue_0'
                   WHEN due >= CURRENT_DATE - INTERVAL '12 months' THEN 'overdue_6'
                   ELSE 'overdue_12'
               END AS bucket,
               COUNT(*) AS cnt,
               COALESCE(SUM(plan), 0) AS plan_sum
        FROM (
            SELECT cfo, plan, to_date(plan_date, 'YYYY.MM') AS due
            FROM igk_stat_data
            WHERE {year_col} = TRUE
              AND igk = %s
              AND status IN ({not_concl})
              AND cfo IS NOT NULL AND TRIM(cfo) <> ''
              AND plan_date IS NOT NULL AND TRIM(plan_date) <> ''
        ) src
        GROUP BY 1, 2
    """
    return sql, [igk, *NOT_CONCL]


def znp_by_cfo(year_col, igk):
    concluded = ", ".join(["%s"] * len(CONCLUDED))
    sql = f"""
        SELECT cfo, stage, COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS plan_sum
        FROM (
            SELECT i.cfo,
                   CASE
                       WHEN z.id IS NULL THEN 'not_issued'
                       WHEN z.znp_status = '{ZNP_PENDING}' THEN 'in_progress'
                       WHEN z.fact_sum IS NOT NULL THEN 'paid'
                       ELSE 'issued'
                   END AS stage,
                   COALESCE(z.plan_sum, i.plan) AS amount
            FROM igk_stat_data i
            LEFT JOIN znp_data z ON z.parent_id = i.pp_id
            WHERE i.igk = %s
              AND i.status IN ({concluded})
              AND i.{year_col} = TRUE
              AND i.cfo IS NOT NULL AND TRIM(i.cfo) <> ''
              AND i.payment_type IN ('{ADVANCE}', '{POSTPAYMENT}')
        ) src
        GROUP BY 1, 2
    """
    return sql, [igk, *CONCLUDED]


def znp_sap_by_cfo(igk):
    allowed_cfo = [str(n) for n in range(420, 430)]
    cfo_ph = ", ".join(["%s"] * len(allowed_cfo))
    igk_filter = "AND igk = %s" if igk else ""
    params = list(allowed_cfo)
    if igk:
        params.append(igk)
    sql = f"""
        SELECT cfo,
               CASE
                   WHEN stage_e IS NULL THEN 'waiting'
                   WHEN stage_f IS NULL THEN 'sent'
                   WHEN normalize_doc_num IS NOT NULL THEN 'paid'
                   ELSE 'confirmed'
               END AS stage,
               COUNT(*) AS cnt,
               COALESCE(SUM(vv_sum), 0) AS plan_sum
        FROM znp_data_sap
        WHERE cfo IN ({cfo_ph})
          {igk_filter}
        GROUP BY 1, 2
    """
    return sql, params
