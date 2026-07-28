"""Помесячные разрезы для графиков.

Каждая функция возвращает пару (sql, params) — так же, как kdr_delta в
queries.py. Результат всегда приводится к 12 месяцам в api.py, поэтому пустые
месяцы не теряются и график не съезжает.

Откуда берётся месяц:
- договоры      — igk_stat_data.plan_date, строка вида "ГГГГ.ММ" (формат
                  проверен: все строки в базе ему соответствуют);
- ЗНП (ФЗД)     — znp_data.plan_payment_date и fact_payment_date, обе DateField;
- ЗНП (SAP)     — znp_data_sap.stage_e / stage_f / payment_possible, DateField.
"""

from .queries import CONCLUDED


def contracts_monthly(year, igk):
    """Авансы по месяцам: плановая сумма против фактической."""
    sql = """
        SELECT substring(plan_date, 6, 2) AS m,
               COALESCE(SUM(plan), 0) AS plan_sum,
               COALESCE(SUM(fact), 0) AS fact_sum
        FROM igk_stat_data
        WHERE plan_date LIKE %s
          AND payment_type = 'Аванс'
          AND status <> 'Расторгнут'
          AND igk = %s
        GROUP BY 1
        ORDER BY 1
    """
    return sql, [f"{year}.%", igk]


def znp_monthly(year, igk):
    """ЗНП (ФЗД): планируемые платежи против прошедших.

    План и факт живут в разных колонках дат, поэтому месяц у них считается
    независимо — заявка попадает в один месяц по плану и в другой по факту.
    Отсюда UNION ALL, а не два FILTER-агрегата по одной дате.
    """
    concluded = ", ".join(["%s"] * len(CONCLUDED))
    sql = f"""
        SELECT m,
               COALESCE(SUM(plan_sum), 0) AS plan_sum,
               COALESCE(SUM(fact_sum), 0) AS fact_sum
        FROM (
            SELECT to_char(z.plan_payment_date, 'MM') AS m,
                   z.plan_sum AS plan_sum, 0 AS fact_sum
            FROM znp_data z
            JOIN igk_stat_data i ON i.pp_id = z.parent_id
            WHERE i.igk = %s AND i.status IN ({concluded})
              AND z.plan_payment_date IS NOT NULL
              AND EXTRACT(YEAR FROM z.plan_payment_date) = %s
            UNION ALL
            SELECT to_char(z.fact_payment_date, 'MM') AS m,
                   0 AS plan_sum, z.fact_sum AS fact_sum
            FROM znp_data z
            JOIN igk_stat_data i ON i.pp_id = z.parent_id
            WHERE i.igk = %s AND i.status IN ({concluded})
              AND z.fact_payment_date IS NOT NULL
              AND EXTRACT(YEAR FROM z.fact_payment_date) = %s
        ) t
        GROUP BY m
        ORDER BY m
    """
    params = [igk, *CONCLUDED, year, igk, *CONCLUDED, year]
    return sql, params


def znp_sap_monthly(year, igk):
    """ЗНП (SAP): сколько заявок прошло каждый этап в каждом месяце.

    Этапы упорядочены (передано -> подтверждено -> можно платить), у каждого
    своя дата, поэтому месяцы считаются по трём колонкам независимо.
    """
    # тот же список ЦФО, что и на самой странице (pages.py::znp_sap_table):
    # строковый BETWEEN сюда не годится — под него попало бы и "4200"
    allowed_cfo = [str(n) for n in range(420, 430)]
    cfo_ph = ", ".join(["%s"] * len(allowed_cfo))
    igk_filter = "AND igk = %s" if igk else ""

    parts = []
    params = []
    for column in ("stage_e", "stage_f", "payment_possible"):
        parts.append(f"""
            SELECT to_char({column}, 'MM') AS m, '{column}' AS stage,
                   1 AS cnt, COALESCE(vv_sum, 0) AS amount
            FROM znp_data_sap
            WHERE {column} IS NOT NULL
              AND EXTRACT(YEAR FROM {column}) = %s
              AND cfo IN ({cfo_ph})
              {igk_filter}
            """)
        params.append(year)
        params.extend(allowed_cfo)
        if igk:
            params.append(igk)

    sql = f"""
        SELECT m, stage, SUM(cnt) AS cnt, SUM(amount) AS amount
        FROM ({" UNION ALL ".join(parts)}) t
        GROUP BY m, stage
        ORDER BY m
    """
    return sql, params
