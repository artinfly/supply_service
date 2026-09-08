"""
Модуль SQL-запросов и общих констант для отчётов и реестров.

Содержит:
- Константы статусов, типов платежей и годов
- Вспомогательные функции для валидации и форматирования
- SQL-шаблоны для реестров, истории, дубликатов и выгрузок
- Функции для получения уникальных значений (ИГК, ЦФО, контрагенты)

Все SQL-запросы возвращают строки с агрегированными данными для отображения
на страницах реестров и в Excel-выгрузках. Суммы округляются до 2 знаков,
крупные суммы переводятся в миллионы рублей (деление на 1e6).
"""

from datetime import datetime

from django.utils import timezone

# ============================================================================
# Константы статусов и типов платежей
# ============================================================================

# Статусы заключённых договоров (попадают в сводки как "заключено")
CONCLUDED = (
    "Исполняется",
    "Возвращен на уточнение",
    "На согласовании",
    "Подписан",
    "На утверждении",
    "Исполнен",
)

# Статусы незаключённых договоров (черновики)
NOT_CONCL = ("Черновик",)

# Статус расторгнутого договора (исключается из большинства сводок)
TERMINATED = ("Расторгнут",)

# Типы платежей
ADVANCE = "Аванс"
POSTPAYMENT = "Постоплата"

# Статус утверждённой заявки ФЗД
ZNP_APPROVED = "Утвержден"

# Доступные годы для отчётов (добавление нового года требует правки моделей и normalize.py)
YEARS = [2025, 2026, 2027]

# Маппинг года на имя колонки-флага в таблице igk_stat_data: "2025" -> "y25"
YEAR_COL = {str(y): f"y{str(y)[2:]}" for y in YEARS}

# SQL-условие "у строки есть заказ" (order не пустой и не состоит из пробелов)
# Используется в большинстве запросов для фильтрации валидных строк
HAS_ORDER = '"order" IS NOT NULL AND TRIM("order") != \'\''

# Перечень ЦФО, которые попадают в сводку SAP (420-429)
SAP_CFO = tuple(str(n) for n in range(420, 430))


# ============================================================================
# Вспомогательные функции валидации и форматирования
# ============================================================================


def valid_date(value):
    """
    Проверяет, является ли строка валидной датой в формате YYYY-MM-DD.

    Используется для валидации параметров периода в графиках.
    Возвращает True если дата корректна, False иначе.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def valid_year(value):
    """
    Приводит значение к валидному году из списка YEARS.

    Если значение не является числом или не входит в YEARS, возвращает последний год из списка.
    Используется для безопасной обработки параметров года из HTTP-запросов.
    """
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = timezone.localdate().year
    return year if year in YEARS else YEARS[-1]


def needs_znp(alias="i"):
    """
    Возвращает SQL-выражение для условия "остаток превышает допуск".

    Логика: остаток (remainder) должен быть больше, чем допуск в рублях.
    Допуск рассчитывается как процент (tolerance) от суммы договора (contract_sum).

    Параметр alias позволяет указать алиас таблицы в SQL-запросе (по умолчанию "i").
    Если alias пустой, префикс таблицы не добавляется.

    Используется для определения позиций, по которым нужно выдать заявку на платёж.
    """
    p = f"{alias}." if alias else ""
    return (
        f"COALESCE({p}remainder, 0) > "
        f"GREATEST(COALESCE({p}tolerance, 0) * COALESCE({p}contract_sum, 0) / 100.0, 0)"
    )


def _sl(statuses):
    """
    Форматирует кортеж статусов в строку для SQL-запроса.

    Преобразует ("Статус1", "Статус2") в "'Статус1', 'Статус2'" для использования в IN (...).
    """
    return ", ".join(f"'{s}'" for s in statuses)


def escape_like(value):
    """
    Экранирует специальные символы для SQL-оператора LIKE.

    Заменяет обратный слэш, процент и подчёркивание на их экранированные версии.
    Это позволяет искать literal строки, содержащие эти символы.

    ВАЖНО: В SQL-запросах, где используется эта функция, нужно указать ESCAPE '\'
    чтобы PostgreSQL корректно интерпретировал экранирование.
    """
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ============================================================================
# SQL-запросы для реестров и сводок
# ============================================================================


def kdr(year):
    """
    SQL-запрос для таблицы "Контроль договорной работы" за год.

    Возвращает агрегаты по каждому ИГК:
    - Количество договоров с заказом и их сумма
    - Количество заключённых договоров и их сумма
    - Количество договоров за текущий год (не расторгнутых)
    - Количество заключённых за текущий год
    - План и факт авансов за текущий год
    - Количество незаключённых за текущий год
    - Проценты заключённых (по количеству и сумме)
    - Процент оплаченных авансов

    Все суммы переводятся в миллионы рублей.
    """
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


# SQL-шаблон для агрегатов по ИГК (используется в igk_stat и igk_stat_total)
# Считает: сумму спецификаций, сумму и факт авансов, проценты, остатки, количество позиций
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
    """
    SQL-запрос для реестра ИГК по годам (заключённые/незаключённые/расторгнутые).

    Возвращает агрегаты по каждому ИГК для выбранного года и статуса.
    """
    body = _IGK_STAT_COLS.format(yc=yc, sl=_sl(statuses))
    return f"""
    SELECT igk,{body}
    GROUP BY igk ORDER BY igk
    """


def igk_stat_total(yc, statuses):
    """
    SQL-запрос для итоговой строки реестра ИГК.

    Возвращает агрегаты по всем ИГК (одна строка с меткой 'ИТОГО').
    """
    body = _IGK_STAT_COLS.format(yc=yc, sl=_sl(statuses))
    return f"""
    SELECT 'ИТОГО' AS igk,{body}
    """


# SQL-шаблоны для запросов истории изменений
# JOIN связывает contracts_history с igk_stat_data через MD5-хеш позиции
_HISTORY_JOIN = """
    FROM contracts_history ch
    LEFT JOIN igk_stat_data isd ON ch.hash = digest(
        concat(isd.igk, isd.c_agent, isd.contract, isd.item,
               isd."order", TRIM(isd.stage), isd.plan_date), 'md5')
"""

# Группировка для запросов истории
_HISTORY_GROUP = """
    isd.igk, isd.c_agent, isd.cfo, isd.contract, isd.item,
    isd.payment_type, isd."order", ch.update_date, ch.upload_date, isd.c_date
"""


def history_status():
    """
    SQL-запрос для таблицы "История изменений статуса".

    Показывает изменения статуса договоров с датами изменения и загрузки.
    """
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
    """
    SQL-запрос для таблицы "История изменений плана".

    Показывает изменения плановых сумм с процентами от суммы договора.
    """
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
    """
    SQL-запрос для таблицы "История изменений факта".

    Показывает изменения фактических сумм оплат.
    """
    return f"""
        SELECT RIGHT(isd.igk, 4) AS igk, isd.c_agent, isd.cfo, isd.contract,
            isd.payment_type, isd.item, ch.old_fact, ch.new_fact,
            ch.fact_changed_date, isd.c_date
        {_HISTORY_JOIN}
        WHERE ch.fact_changed_date IS NOT NULL
        GROUP BY {_HISTORY_GROUP}, ch.old_fact, ch.new_fact, ch.fact_changed_date
        ORDER BY ch.fact_changed_date DESC NULLS LAST
    """


# ============================================================================
# SQL-запросы для поиска дубликатов
# ============================================================================


def dupes_filter(cfo, year):
    """
    Формирует условия WHERE для фильтров дубликатов по ЦФО и году.

    Возвращает кортеж: (список условий SQL, список параметров)
    """
    conditions = []
    params = []
    if cfo:
        conditions.append("TRIM(cfo) = %s")
        params.append(cfo)
    if year in YEAR_COL:
        conditions.append(f"{YEAR_COL[year]} = TRUE")
    return conditions, params


def contract_dupes(cfo=None, year=None):
    """
    SQL-запрос для поиска полных дубликатов строк договоров.

    Группирует по всем ключевым полям (ИГК, контрагент, договор, предмет, заказ, этап, дата).
    Возвращает только группы с COUNT(*) > 1.

    Дополнительно вычисляет MD5-хеш позиции для отображения в интерфейсе.
    """
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
    """
    SQL-запрос для поиска дубликатов по заказу (ИГК + предмет + заказ).

    Показывает случаи, когда один и тот же заказ встречается в разных договорах
    или у разных контрагентов.

    Возвращает количество строк, уникальных договоров и контрагентов в каждой группе.
    """
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
    """
    SQL-запрос для детализации по одному ИГК за год.

    Показывает позиции договоров, входящих в выбранный ИГК, сгруппированные
    по договору, контрагенту, статусу, типу платежа, предмету, заказу и этапу.
    """
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
    """
    SQL-запросы для реестра всех договоров с фильтрами.

    Возвращает два запроса:
    - detail: детальные строки по каждой позиции договора
    - total: итоговые строки по группам (ИГК, договор, заказ)

    Оба запроса используют одинаковую группировку и условия WHERE.
    Итоговые строки помечаются флагом is_subtotal=1 для отображения в интерфейсе.
    """
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
    """
    SQL-запрос для выгрузки авансов по шаблону.

    Группирует по договору и заказу, показывает план и факт авансов.
    Учитывает допуск (tolerance) при расчёте плановой суммы.

    Статус договора определяется как "Заключён" или "Не заключён" на основе
    максимального статуса в группе.
    """
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
    """
    SQL-запрос для Excel-выгрузки "Контроль договорной работы" за год.

    Группирует по ИГК и ЦФО, показывает агрегаты по всем договорам и за выбранный год.
    """
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
    """
    SQL-запрос для расчёта дельты заключённых договоров между двумя датами.

    Сравнивает снимки contract_counts_snapshot за start_date и end_date.
    Возвращает разницу в количестве заключённых договоров по каждому ИГК и ЦФО.

    Использует FULL OUTER JOIN чтобы учесть комбинации, появившиеся или исчезнувшие
    между датами.
    """
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
    """
    Формирует условия WHERE для выгрузки договоров по контрагенту.

    Базовые условия: выбранный год, непустой договор, непустой тип платежа.
    Если указан агент, добавляется фильтр по контрагенту через ILIKE с экранированием.

    ВАЖНО: В SQL-запросе нужно указать ESCAPE '\' для корректной работы escape_like.

    Возвращает кортеж: (список условий SQL, список параметров)
    """
    conditions = [
        f"{yc}=TRUE",
        "contract IS NOT NULL AND TRIM(contract)!=''",
        "payment_type IS NOT NULL AND TRIM(payment_type)!=''",
    ]
    params = []
    if agent:
        conditions.append("c_agent ILIKE %s ESCAPE '\\'")
        params.append(f"%{escape_like(agent)}%")
    return conditions, params


def export_contracts_by_agent(conditions):
    """
    SQL-запрос для выгрузки договоров по контрагенту в Excel.

    Группирует по всем ключевым полям, показывает план, факт и остаток.
    """
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


# ============================================================================
# Функции для получения уникальных значений (фильтры на страницах)
# ============================================================================


def distinct_igk_suffixes():
    """
    SQL-запрос для получения уникальных суффиксов ИГК (последние 4 символа).

    Используется для выпадающего списка фильтров на страницах реестров.
    """
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM igk_stat_data
        WHERE igk IS NOT NULL ORDER BY RIGHT(igk, 4)
    """


def distinct_cfo():
    """
    SQL-запрос для получения уникальных ЦФО.

    Используется для выпадающего списка фильтров на страницах реестров.
    """
    return """
        SELECT DISTINCT cfo FROM igk_stat_data
        WHERE cfo IS NOT NULL AND TRIM(cfo) != ''
        ORDER BY cfo
    """


def distinct_sap_igk():
    """
    SQL-запрос для получения уникальных суффиксов ИГК из заявок SAP.
    """
    return """
        SELECT DISTINCT RIGHT(igk, 4) FROM znp_data_sap
        WHERE igk IS NOT NULL AND TRIM(igk) != ''
        ORDER BY 1
    """


def distinct_sap_cfo():
    """
    SQL-запрос для получения уникальных ЦФО из заявок SAP (только из диапазона 420-429).
    """
    return f"""
        SELECT DISTINCT cfo FROM znp_data_sap
        WHERE cfo IN ({_sl(SAP_CFO)})
        ORDER BY cfo
    """


def distinct_agents():
    """
    SQL-запрос для получения уникальных контрагентов.

    Используется для выпадающего списка на странице выгрузок.
    """
    return """
        SELECT DISTINCT c_agent FROM igk_stat_data
        WHERE c_agent IS NOT NULL AND TRIM(c_agent) != ''
        ORDER BY c_agent
    """


def znp_list(where):
    """
    SQL-запрос для реестра заявок ФЗД.

    Показывает позиции договоров с LEFT JOIN на заявки.
    Вычисляет человекочитаемый статус заявки на основе типа платежа и наличия оплаты.

    Статусы:
    - "На оформлении ЗнП": заявка есть, но не утверждена
    - "Не оформлено (Аванс/Постоплата)": заявки нет, но остаток превышает допуск
    - "Оплачено ЗнП (Аванс/Постоплата)": заявка утверждена и оплачена
    - "Оформлено ЗнП (Аванс/Постоплата)": заявка утверждена, но не оплачена
    """
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
    """
    SQL-запрос для журнала появившихся договоров.

    Параметр kind фильтрует по типу появления: "новый" или "изменил статус".
    """
    return """
        SELECT upload_date, reason, RIGHT(igk, 4) AS igk, cfo, c_agent, contract, item, order_num, stage, plan_date, status, plan, contract_sum
        FROM contracts_appeared
        WHERE kind = %s
        ORDER BY upload_date DESC, igk, contract, item
    """, [
        kind
    ]
