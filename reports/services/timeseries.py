"""Помесячные разрезы для графиков под таблицами ЦФО.

Каждая функция возвращает пару (sql, params), как kdr_delta в queries.py.
Месяц всегда приходит строкой "ГГГГ.ММ" — ось строится по год-месяцам, а не по
двенадцати месяцам одного года: у договора ГодИГК 2027 платежи по графику могут
приходиться на 2024 год, и при фиксированных 12 месяцах они бы просто пропали.

Год везде берётся тот же, что в селекторе страницы, — флаг ГодИГК (y25/y26/y27).
Исключение — SAP: там у заявок нет привязки к ГодИГК, и разрез идёт по датам
самих этапов согласования.
"""

from .queries import CONCLUDED, NOT_CONCL


def contracts_monthly(year_col, igk):
    """Контрактация по месяцам графика платежей: заключено против незаключённого.

    Те же метрики, что в карточках и таблице ЦФО этой страницы. Видно, к каким
    месяцам подходят платежи по договорам, которые ещё не заключены.
    """
    concluded = ", ".join(["%s"] * len(CONCLUDED))
    not_concl = ", ".join(["%s"] * len(NOT_CONCL))
    sql = f"""
        SELECT substring(plan_date, 1, 7) AS ym,
               COALESCE(SUM(plan) FILTER (WHERE status IN ({concluded})), 0) AS concluded_sum,
               COALESCE(SUM(plan) FILTER (WHERE status IN ({not_concl})), 0) AS not_concluded_sum
        FROM igk_stat_data
        WHERE {year_col} = TRUE
          AND igk = %s
          AND plan_date IS NOT NULL AND TRIM(plan_date) <> ''
          AND status <> 'Расторгнут'
        GROUP BY 1
        ORDER BY 1
    """
    return sql, [*CONCLUDED, *NOT_CONCL, igk]


def znp_monthly(year_col, igk):
    """ЗНП (ФЗД) по месяцам: оформлено против оплаченного.

    Те же две величины, что на карточках страницы. План и факт живут в разных
    колонках дат, поэтому месяц у них считается независимо: заявка попадает в
    один месяц по плановой дате и в другой по фактической. Отсюда UNION ALL,
    а не два FILTER-агрегата по одной дате.
    """
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


# этап «Оплачено» в разрез не попадает: у него нет своей даты, только номер
# документа нормализации без отметки времени
SAP_STAGE_COLUMNS = ("stage_e", "stage_f", "payment_possible")


def znp_sap_monthly(igk):
    """ЗНП (SAP): сколько заявок прошло каждый этап согласования в месяце.

    Те же этапы, что на карточках страницы. У каждого своя дата, поэтому месяцы
    считаются по трём колонкам независимо.
    """
    # тот же список ЦФО, что и на самой странице (pages.py::znp_sap_table):
    # строковый BETWEEN сюда не годится — под него попало бы и "4200"
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
