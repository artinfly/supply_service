"""SQL-запросы и константы для работы с базой данных."""

from datetime import datetime

from django.db import connection
from django.utils import timezone

# --- Константы статусов и типов ---


CONCLUDED = (
    "Исполняется",
    "Возвращен на уточнение",
    "На согласовании",
    "Подписан",
    "На утверждении",
    "Исполнен",
    "Приостановлен",
)

NOT_CONCL = ("Черновик",)
TERMINATED = ("Расторгнут",)

ADVANCE = "Аванс"
POSTPAYMENT = "Постоплата"

ZNP_APPROVED = "Утвержден"


# Условие наличия заказа (используется в фильтрации)
HAS_ORDER = '"order" IS NOT NULL AND TRIM("order") != \'\''

# Допустимые ЦФО для SAP
SAP_CFO = tuple(str(n) for n in range(420, 430))


# --- Утилиты валидации и форматирования ---


def dict_rows(cursor):
    """Строки результата SQL-запроса как словари {колонка: значение}."""
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def valid_date(value):
    """Проверяет, является ли строка валидной датой в формате ГГГГ-ММ-ДД."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


# --- Годы ---
# Год позиции договора хранится в igk_stat_data.c_date — 4 цифры из колонки
# «ГодИГК» («2026»). Список годов берётся из загруженных данных, поэтому новый год
# появляется на страницах сам, без правок кода и миграций.


def available_years():
    """Годы для выбора на страницах: все годы из договоров + текущий год, по возрастанию."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT c_date FROM igk_stat_data WHERE c_date ~ '^[0-9]{4}$'"
        )
        years = {int(row[0]) for row in cur.fetchall()}
    years.add(timezone.localdate().year)
    return sorted(years)


def default_year():
    """Год по умолчанию — последний из доступных."""
    return available_years()[-1]


def valid_year(value):
    """Год из списка available_years(); если такого нет — последний доступный."""
    years = available_years()
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = timezone.localdate().year
    return year if year in years else years[-1]


def parse_year(value):
    """Год из адреса или параметра запроса, если он есть в available_years().

    «2026» -> 2026; неизвестный год или мусор -> None.
    """
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if year in available_years() else None


def year_sql(year, alias=""):
    """SQL-условие «позиция этого года»: c_date = '2026'.

    year приводится к int, поэтому подставлять его в текст запроса безопасно.
    alias — префикс таблицы, например «i.».
    """
    return f"{alias}c_date = '{int(year)}'"


def needs_znp(alias="i"):
    """Возвращает SQL-условие: остаток больше допустимого отклонения (tolerance)."""
    p = f"{alias}." if alias else ""
    return (
        f"COALESCE({p}remainder, 0) > "
        f"GREATEST(COALESCE({p}tolerance, 0) * COALESCE({p}contract_sum, 0) / 100.0, 0)"
    )


def _sl(statuses):
    """Преобразует кортеж статусов в строку для SQL IN (...).

    Только для констант из этого модуля (CONCLUDED, SAP_CFO и т.п.):
    значения подставляются в SQL как есть. Ввод пользователя — только через %s.
    """
    return ", ".join(f"'{s}'" for s in statuses)


def escape_like(value):
    """Экранирует спецсимволы для использования в SQL LIKE с ESCAPE '\\'."""
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- Запросы: КДР (Контрактация договоров) ---


def kdr(year):
    """SQL сводки КДР по ИГК за год (страница «КДР»).

    Считаются только позиции с заполненным заказом (HAS_ORDER), группировка
    по полному номеру ИГК. Выгрузка КДР в Excel (kdr_export) считает иначе:
    все позиции и группировка по последним 4 цифрам — поэтому цифры
    на экране и в файле могут расходиться.
    """
    yc = year_sql(year)
    cl = _sl(CONCLUDED)
    nl = _sl(NOT_CONCL)
    return f"""
    SELECT igk,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER}) AS orders,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER}), 0)/1e6 AS numeric), 2) AS order_sum,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND status IN ({cl})) AS count_concluded,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND status IN ({cl})), 0)/1e6 AS numeric), 2) AS concluded_order_sum,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc} AND status!='Расторгнут') AS count_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS order_sum_curr_year,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc} AND status IN ({cl})) AS count_concluded_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND status IN ({cl})), 0)/1e6 AS numeric), 2) AS concluded_order_sum_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS pp_sum_plan,
        ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE {HAS_ORDER} AND {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0)/1e6 AS numeric), 2) AS pp_sum_fact,
        COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND status IN ({nl}) AND {yc}) AS count_not_concluded_curr_year,
        ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND status IN ({nl})), 0)/1e6 AS numeric), 2) AS not_concluded_order_sum_curr_year,
        CASE WHEN COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc} AND status!='Расторгнут') = 0 THEN 0
             ELSE CAST(COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc} AND status IN ({cl})) * 100.0
                  / NULLIF(COUNT(DISTINCT contract) FILTER (WHERE {HAS_ORDER} AND {yc} AND status!='Расторгнут'), 0) AS int)
        END AS count_concluded_percent_curr_year,
        CASE WHEN COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND status!='Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND status IN ({cl})), 0) * 100.0
                  / NULLIF(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND status!='Расторгнут'), 0) AS int)
        END AS order_sum_percent_curr_year,
        CASE WHEN COALESCE(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0) = 0 THEN 0
             ELSE CAST(COALESCE(SUM(fact) FILTER (WHERE {HAS_ORDER} AND {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0)
                  / NULLIF(SUM(plan) FILTER (WHERE {HAS_ORDER} AND {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'), 0) * 100 AS int)
        END AS pp_percent
    FROM igk_stat_data
    GROUP BY igk ORDER BY igk
    """


# --- Запросы: Статистика по ИГК ---


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
    WHERE {{yc}} AND status IN ({{sl}})
"""


def igk_stat(yc, statuses):
    """Возвращает SQL для статистики по ИГК (группировка по igk)."""
    body = _IGK_STAT_COLS.format(yc=yc, sl=_sl(statuses))
    return f"""
    SELECT igk,{body}
    GROUP BY igk ORDER BY igk
    """


def igk_stat_total(yc, statuses):
    """Возвращает SQL для итоговой строки статистики по ИГК."""
    body = _IGK_STAT_COLS.format(yc=yc, sl=_sl(statuses))
    return f"""
    SELECT 'ИТОГО' AS igk,{body}
    """


# --- Запросы: История изменений ---


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
    """Возвращает SQL для истории изменений статусов договоров."""
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
    """Возвращает SQL для истории изменений плановых сумм."""
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
    """Возвращает SQL для истории изменений фактических сумм."""
    return f"""
        SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
            isd.payment_type, isd.item, ch.old_fact, ch.new_fact,
            ch.fact_changed_date, isd.c_date
        {_HISTORY_JOIN}
        WHERE ch.fact_changed_date IS NOT NULL
        GROUP BY {_HISTORY_GROUP}, ch.old_fact, ch.new_fact, ch.fact_changed_date
        ORDER BY ch.fact_changed_date DESC NULLS LAST
    """


# --- Запросы: Дубликаты ---


def dupes_filter(cfo, year):
    """Формирует условия и параметры для фильтрации дубликатов по ЦФО и году."""
    conditions = []
    params = []
    if cfo:
        conditions.append("TRIM(cfo) = %s")
        params.append(cfo)
    year = parse_year(year)
    if year:
        conditions.append(year_sql(year))
    return conditions, params


def contract_dupes(cfo=None, year=None):
    """Возвращает SQL для поиска полных дубликатов договоров."""
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
    """Возвращает SQL для поиска дубликатов по номеру заказа."""
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


# --- Запросы: Детализация и реестры ---


def igk_detail(year, igk, statuses):
    """Возвращает SQL для детализации договоров по конкретному ИГК."""
    yc = year_sql(year)
    sl = _sl(statuses)
    return f"""
        SELECT contract, c_agent, status,
            COALESCE(payment_type,'ИНОЕ') AS payment_type,
            item, "order", TRIM(stage) AS stage,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS plan_sum,
            ROUND(CAST(SUM(fact) AS numeric), 2) AS fact_sum,
            ROUND(CAST(SUM(plan)-SUM(COALESCE(fact,0)) AS numeric), 2) AS remain
        FROM igk_stat_data
        WHERE igk LIKE %s AND {yc} AND status IN ({sl})
          AND payment_type IS NOT NULL AND TRIM(payment_type) != ''
        GROUP BY contract, c_agent, status, payment_type, item, "order", stage
        ORDER BY contract, payment_type
    """


# Поля, по которым строки реестра «Все договоры» собираются в подытог по договору.
# Должны совпадать в GROUP BY запроса итогов и в ключе группировки в api_all_contracts.
ALL_CONTRACTS_GROUP = ("igk", "c_agent", "contract", "status", "item", "order")


def all_contracts(where):
    """Два SQL-запроса реестра «Все договоры»: строки позиций и подытоги по договору.

    Подытог считается по договору целиком, через все годы (год в GROUP BY не
    входит): иначе у договора с этапами в разных годах получалось бы несколько
    подытогов.
    """
    detail = f"""
        SELECT igk, c_agent, contract, status,
            COALESCE(payment_type,'ИНОЕ') AS payment_type,
            item, "order", TRIM(stage) AS stage, c_date,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact,0)) AS numeric), 2) AS pp_remain,
            0 AS is_subtotal
        FROM igk_stat_data {where}
        GROUP BY igk, c_agent, contract, status, payment_type, item, "order", stage, c_date
        ORDER BY igk NULLS LAST, contract, payment_type, stage
    """
    total = f"""
        SELECT igk, c_agent, contract, status,
            'ИТОГО' AS payment_type,
            item, "order", NULL AS stage,
            NULL AS c_date,
            ROUND(CAST(SUM(plan) AS numeric), 2) AS spec_sum,
            ROUND(CAST(SUM(plan) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_sum,
            ROUND(CAST(SUM(fact) FILTER (WHERE payment_type='{ADVANCE}') AS numeric), 2) AS pp_fact,
            ROUND(CAST(SUM(plan) - SUM(COALESCE(fact,0)) AS numeric), 2) AS pp_remain,
            1 AS is_subtotal
        FROM igk_stat_data {where}
        GROUP BY igk, c_agent, contract, status, item, "order"
        ORDER BY igk NULLS LAST, contract
    """
    return detail, total


# --- Запросы: Экспорт ---


def advances(year):
    """Возвращает SQL для экспорта отчёта по авансам."""
    yc = year_sql(year)
    # «Заключён» — если хотя бы одна позиция договора в статусе из CONCLUDED,
    # как на сводках. Раньше бралось MAX(status) (по алфавиту), и «Приостановлен»
    # считался незаключённым, хотя на сводках он заключённый.
    return f"""
        SELECT MAX(igk) AS igk, MAX(c_agent) AS c_agent, MAX(cfo) AS cfo, contract,
            CASE WHEN BOOL_OR(status IN ({_sl(CONCLUDED)})) THEN 'Заключён' ELSE 'Не заключён' END AS state,
            MAX(payment_type) AS payment_type, MAX(item) AS item, "order" AS qty,
            ROUND(CAST(SUM(CASE WHEN tolerance>0 THEN plan*(1+tolerance/100.0) ELSE plan END) AS numeric),2) AS spec_sum,
            ROUND(CAST(SUM(CASE WHEN payment_type='{ADVANCE}' AND tolerance>0 THEN plan*(1+tolerance/100.0)
                              WHEN payment_type='{ADVANCE}' THEN plan ELSE 0 END) AS numeric),2) AS advance_plan,
            ROUND(CAST(SUM(CASE WHEN payment_type='{ADVANCE}' THEN COALESCE(fact,0) ELSE 0 END) AS numeric),2) AS advance_fact
        FROM igk_stat_data
        WHERE {yc} AND status!='Расторгнут'
          AND payment_type IN ('{ADVANCE}','{POSTPAYMENT}')
          AND igk IS NOT NULL AND TRIM(igk)!=''
          AND cfo IS NOT NULL AND TRIM(cfo)!=''
          AND contract IS NOT NULL AND TRIM(contract)!=''
        GROUP BY contract, "order"
        ORDER BY MAX(igk), MAX(cfo), contract, "order"
    """


def kdr_export(year):
    """SQL выгрузки КДР в Excel: строки по ИГК (последние 4 цифры) и ЦФО.

    В отличие от kdr() учитывает и позиции без заказа (см. комментарий там).
    """
    yc = year_sql(year)
    cl = _sl(CONCLUDED)
    nl = _sl(NOT_CONCL)
    return f"""
        SELECT MAX(igk) AS igk, cfo,
            COUNT(DISTINCT contract) AS total_count,
            ROUND(CAST(COALESCE(SUM(plan),0)/1e6 AS numeric),2) AS total_sum,
            COUNT(DISTINCT contract) FILTER (WHERE status IN ({cl})) AS concl_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE status IN ({cl})),0)/1e6 AS numeric),2) AS concl_sum,
            COUNT(DISTINCT contract) FILTER (WHERE {yc} AND status!='Расторгнут') AS year_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc} AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS year_sum,
            COUNT(DISTINCT contract) FILTER (WHERE {yc} AND status IN ({cl})) AS year_concl_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc} AND status IN ({cl})),0)/1e6 AS numeric),2) AS year_concl_sum,
            COUNT(DISTINCT contract) FILTER (WHERE {yc} AND status IN ({nl})) AS year_not_concl_count,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc} AND status IN ({nl})),0)/1e6 AS numeric),2) AS year_not_concl_sum,
            ROUND(CAST(COALESCE(SUM(plan) FILTER (WHERE {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS pp_plan,
            ROUND(CAST(COALESCE(SUM(fact) FILTER (WHERE {yc} AND payment_type='{ADVANCE}' AND status!='Расторгнут'),0)/1e6 AS numeric),2) AS pp_fact,
            0 AS delta_concl_count
        FROM igk_stat_data
        WHERE igk IS NOT NULL AND TRIM(igk)!='' AND cfo IS NOT NULL AND TRIM(cfo)!=''
        GROUP BY RIGHT(igk,4), cfo
        ORDER BY igk, cfo
    """


def kdr_delta(year, start_date, end_date):
    """Возвращает SQL и параметры для расчёта дельты заключённых договоров между двумя датами."""
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
        str(year),
        end_date,
        str(year),
    ]


def contracts_by_agent_filter(year, agent):
    """Формирует условия и параметры для фильтрации договоров по контрагенту."""
    conditions = [
        year_sql(year),
        "contract IS NOT NULL AND TRIM(contract)!=''",
        "payment_type IS NOT NULL AND TRIM(payment_type)!=''",
    ]
    params = []
    if agent:
        conditions.append("c_agent ILIKE %s ESCAPE '\\'")
        params.append(f"%{escape_like(agent)}%")
    return conditions, params


def export_contracts_by_agent(conditions):
    """Возвращает SQL для экспорта договоров по контрагенту."""
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


# --- Запросы: Справочники (DISTINCT) ---


def distinct_igk_suffixes():
    """Возвращает SQL для получения уникальных суффиксов ИГК (последние 4 символа)."""
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM igk_stat_data
        WHERE igk IS NOT NULL ORDER BY RIGHT(igk, 4)
    """


def distinct_cfo():
    """Возвращает SQL для получения уникальных ЦФО."""
    return """
        SELECT DISTINCT cfo FROM igk_stat_data
        WHERE cfo IS NOT NULL AND TRIM(cfo) != ''
        ORDER BY cfo
    """


def distinct_sap_igk():
    """Возвращает SQL для получения уникальных суффиксов ИГК из заявок SAP."""
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM znp_data_sap
        WHERE igk IS NOT NULL AND TRIM(igk) != ''
        ORDER BY 1
    """


def distinct_sap_cfo():
    """Возвращает SQL для получения уникальных ЦФО из заявок SAP."""
    return f"""
        SELECT DISTINCT cfo FROM znp_data_sap
        WHERE cfo IN ({_sl(SAP_CFO)})
        ORDER BY cfo
    """


def distinct_agents():
    """Возвращает SQL для получения уникальных контрагентов."""
    return """
        SELECT DISTINCT c_agent FROM igk_stat_data
        WHERE c_agent IS NOT NULL AND TRIM(c_agent) != ''
        ORDER BY c_agent
    """


# --- Запросы: Заявки на платёж (ЗнП) ---


def znp_list(where):
    """Возвращает SQL для реестра заявок на платёж с объединением данных договора."""
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
    """Возвращает SQL и параметры для получения появившихся договоров указанного типа."""
    return """
        SELECT upload_date, reason, RIGHT(igk, 4) AS igk, cfo, c_agent, contract, item, order_num, stage, plan_date, status, plan, contract_sum
        FROM contracts_appeared
        WHERE kind = %s
        ORDER BY upload_date DESC, igk, contract, item
    """, [
        kind
    ]
