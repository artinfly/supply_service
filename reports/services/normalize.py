"""
Модуль нормализации данных из staging-таблиц в рабочие таблицы.

Конвертирует сырые данные, вычисляет производные поля,
записывает историю изменений и привязывает заявки к договорам.
Все операции выполняются в одной транзакции.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import connection, transaction
from django.utils import timezone

from reports.services.linking import contract_hash, relink_znp_parents
from reports.services.queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    POSTPAYMENT,
    YEARS,
)

# --- Вспомогательные функции конвертации ---


def to_decimal(val):
    """
    Конвертирует строковое значение в Decimal.
    Удаляет пробелы, заменяет запятые на точки.
    Возвращает None для пустых и некорректных значений.
    """
    if val is None or str(val).strip() in ("", "-", "None"):
        return None
    try:
        cleaned = str(val).replace("\xa0", "").replace(" ", "").replace(",", ".")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def year_flags(god_igk):
    """Определяет флаги годов (y25, y26, y27) из колонки «ГодИГК»."""
    try:
        y = int(str(god_igk).strip()[:4])
    except (ValueError, TypeError):
        y = None
    return tuple(y == year for year in YEARS)


def norm(val):
    """Нормализует строковое значение: убирает пробелы, None остаётся None."""
    return str(val).strip() if val is not None else None


def plan_month(val):
    """Извлекает «ГГГГ.ММ» из плановой даты формата «ГГГГ.ММ» или «ММ.ГГГГ»."""
    text = norm(val)
    if not text:
        return None
    parts = text.split(".")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}.{parts[1].zfill(2)}"
    if len(parts) == 2 and len(parts[0]) == 4:
        return f"{parts[0]}.{parts[1].zfill(2)}"
    return None


def values_equal(a, b):
    """Сравнивает два числовых значения с точностью до 2 знаков."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(Decimal(str(a)), 2) == round(Decimal(str(b)), 2)


# --- Константы и маппинги ---

CONCLUDED_SQL = ", ".join(f"'{s}'" for s in CONCLUDED)
YEAR_MAP = [(f"y{str(y)[2:]}", y) for y in YEARS]

MONTH_MAP = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def status_group(status):
    """Определяет группу статуса: 'concluded', 'not_concluded' или None."""
    if status in CONCLUDED:
        return "concluded"
    if status in NOT_CONCL:
        return "not_concluded"
    return None


def _indexed_lookup(rows, key_fn, value_fn):
    """
    Строит индексированный словарь для поиска строк по составному ключу.
    Дубликаты по ключу получают дополнительный индекс (0, 1, 2...).
    """
    counts = defaultdict(int)
    result = {}
    for r in rows:
        base_key = key_fn(r)
        idx = counts[base_key]
        counts[base_key] += 1
        result[base_key + (idx,)] = value_fn(r)
    return result


# --- Функции парсинга дат ---


def text_ru_date_to_date(val):
    """Парсит дату «ДД месяц ГГГГ» (например, «15 сентября 2026»)."""
    if val is None:
        return None
    parts = val.split()
    if len(parts) != 3:
        return None
    day_str, month_str, year_str = parts
    month = MONTH_MAP.get(month_str)
    if month is None:
        return None
    try:
        return date(int(year_str), month, int(day_str))
    except ValueError:
        return None


def dot_date_to_date(val):
    """Парсит дату «ДД.ММ.ГГГГ» или «ГГГГ-ММ-ДД»."""
    if val is None:
        return None
    parts = str(val).strip().split()
    if not parts:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(parts[0], fmt).date()
        except ValueError:
            continue
    return None


# --- Нормализация договоров ---


def normalize_contracts():
    """Нормализует данные договоров из staging_excel в igk_stat_data."""
    with transaction.atomic(), connection.cursor() as cur:
        # Обновление справочника ИГК
        cur.execute("""
            INSERT INTO nsi_igk (igk)
            SELECT DISTINCT TRIM(igk) FROM staging_excel
            WHERE igk IS NOT NULL AND TRIM(igk) <> ''
            ON CONFLICT DO NOTHING
        """)

        # Чтение и конвертация данных из staging
        cur.execute(
            """
            SELECT igk, kontragent, cfo, dogovor, sostoyanie,
                   tip_platezha, predmet, zakaz, plan, fakt,
                   tol, etap_grafika, dataplan, summa_dogovora, god_igk,
                   ostatok
            FROM staging_excel
            WHERE tip_platezha IN (%s, %s)
            """,
            [ADVANCE, POSTPAYMENT],
        )
        staging_rows = cur.fetchall()

        new_data = []
        for r in staging_rows:
            y25, y26, y27 = year_flags(r[14])
            new_data.append(
                (
                    norm(r[0]),  # igk
                    norm(r[1]),  # c_agent
                    norm(r[2]),  # cfo
                    norm(r[3]),  # contract
                    norm(r[4]),  # status
                    norm(r[5]) or None,  # payment_type
                    norm(r[6]),  # item
                    norm(r[7]),  # order
                    to_decimal(r[8]),  # plan
                    to_decimal(r[9]),  # fact
                    to_decimal(r[10]),  # tolerance
                    norm(r[11]),  # stage
                    y25,
                    y26,
                    y27,  # флаги годов
                    plan_month(r[12]),  # plan_date
                    norm(r[14]),  # c_date
                    to_decimal(r[13]),  # contract_sum
                    contract_hash(norm(r[0]), norm(r[1]), norm(r[3]), norm(r[11])),
                    to_decimal(r[15]),  # remainder
                )
            )

        # Загрузка предыдущих данных для сравнения
        cur.execute("""
            SELECT igk, c_agent, contract, item, "order", stage, plan_date,
                   status, plan, fact, contract_sum
            FROM igk_stat_data
            ORDER BY pp_id
        """)
        old_lookup = _indexed_lookup(
            cur.fetchall(),
            key_fn=lambda r: (
                norm(r[0]) or "",
                norm(r[1]) or "",
                norm(r[2]) or "",
                norm(r[3]) or "",
                norm(r[4]) or "",
                norm(r[5]) or "",
                norm(r[6]) or "",
            ),
            value_fn=lambda r: (r[7], r[8], r[9], r[10]),
        )

        new_lookup = _indexed_lookup(
            new_data,
            key_fn=lambda r: (
                r[0] or "",
                r[1] or "",
                r[3] or "",
                r[6] or "",
                r[7] or "",
                r[11] or "",
                r[15] or "",  # plan_date
            ),
            value_fn=lambda r: r,
        )

        # Выявление и запись появившихся договоров
        today = timezone.localdate()
        appeared = []
        if old_lookup:
            for key, row in new_lookup.items():
                kind = status_group(row[4])
                if kind is None:
                    continue
                old_row = old_lookup.get(key)
                if old_row is None:
                    reason = "новая позиция"
                elif status_group(old_row[0]) == kind:
                    continue
                else:
                    reason = "смена статуса"
                appeared.append(
                    (
                        today,
                        kind,
                        reason,
                        row[0],
                        row[2],
                        row[1],
                        row[3],
                        row[6],
                        row[7],
                        row[11],
                        row[15],
                        row[4],
                        row[8],
                        row[17],
                    )
                )
        if appeared:
            cur.executemany(
                """
                INSERT INTO contracts_appeared
                (upload_date, kind, reason, igk, cfo, c_agent, contract,
                 item, order_num, stage, plan_date, status, plan, contract_sum)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                appeared,
            )

        # Выявление и запись истории изменений
        # ВАЖНО: хеш включает все 7 полей ключа (включая plan_date),
        # чтобы совпадать с JOIN в queries.py
        history = []
        for key, new_row in new_lookup.items():
            if key not in old_lookup:
                continue
            old_vals = old_lookup[key]
            old_status, old_plan, old_fact, old_sum = old_vals
            new_status, new_plan = new_row[4], new_row[8]
            new_fact, new_sum = new_row[9], new_row[17]

            status_changed = old_status != new_status
            plan_changed = not values_equal(old_plan, new_plan)
            fact_changed = not values_equal(old_fact, new_fact)
            sum_changed = not values_equal(old_sum, new_sum)

            if not (status_changed or plan_changed or fact_changed or sum_changed):
                continue

            history.append(
                (
                    "".join(key[:-1]),  # конкатенация ключевых полей (без индекса)
                    old_status if status_changed else None,
                    new_status if status_changed else None,
                    today if status_changed else None,
                    today if status_changed else None,
                    old_plan if plan_changed else None,
                    new_plan if plan_changed else None,
                    old_fact if fact_changed else None,
                    new_fact if fact_changed else None,
                    today if plan_changed else None,
                    today if fact_changed else None,
                    old_sum,
                    new_sum,
                )
            )

        if history:
            cur.executemany(
                """
                INSERT INTO contracts_history
                    (hash, old_status, new_status,
                    update_date, upload_date,
                    old_plan, new_plan,
                    old_fact, new_fact,
                    plan_changed_date, fact_changed_date,
                    old_contract_sum, new_contract_sum)
                VALUES (digest(%s, 'md5'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s)
                """,
                history,
            )

        # Полная перезапись igk_stat_data
        cur.execute("TRUNCATE igk_stat_data RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO igk_stat_data
                (igk, c_agent, cfo, contract, status, payment_type,
                 item, "order", plan, fact, tolerance, stage,
                 y25, y26, y27, plan_date, c_date, contract_sum,
                 crc32_hash, remainder)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            new_data,
        )

        # Создание снимков для графиков динамики
        cur.execute(
            "DELETE FROM contract_counts_snapshot WHERE upload_date = %s", [today]
        )
        for year_col, year_val in YEAR_MAP:
            cur.execute(
                f"""
                INSERT INTO contract_counts_snapshot
                    (upload_date, igk, cfo, year_col, concluded_count)
                SELECT %s, RIGHT(igk, 4), cfo, %s, COUNT(DISTINCT contract)
                FROM igk_stat_data
                WHERE {year_col}=TRUE
                  AND status IN ({CONCLUDED_SQL})
                  AND contract IS NOT NULL AND TRIM(contract) != ''
                  AND igk IS NOT NULL AND TRIM(igk) != ''
                  AND cfo IS NOT NULL AND TRIM(cfo) != ''
                GROUP BY RIGHT(igk, 4), cfo
                """,
                [today, year_col],
            )

        # Привязка заявок ФЗД к позициям договоров
        relink_znp_parents()

    return f"обработано строк: {len(new_data)}, изменений записано: {len(history)}"


# --- Нормализация заявок ФЗД ---


def normalize_znp():
    """Нормализует данные заявок ФЗД из staging_znp_excel в znp_data."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT crc32_hash, plan_doc, payment_purpose,
                   plan_payment_date, fact_payment_date,
                   plan_sum, fact_sum, stage, znp_igk,
                   znp_payment_type, znp_status, znp_date
            FROM staging_znp_excel
        """)
        staging_rows = cur.fetchall()

        new_data = []
        for r in staging_rows:
            new_data.append(
                (
                    None,  # parent_id (NULL, привязка позже)
                    norm(r[1]),  # plan_doc
                    norm(r[2]),  # payment_purpose
                    text_ru_date_to_date(norm(r[3])),  # plan_payment_date
                    text_ru_date_to_date(norm(r[4])),  # fact_payment_date
                    to_decimal(r[5]),  # plan_sum
                    to_decimal(r[6]),  # fact_sum
                    r[0],  # crc32_hash
                    norm(r[7]),  # stage
                    norm(r[8]),  # znp_igk
                    norm(r[9]),  # znp_payment_type
                    norm(r[10]),  # znp_status
                    dot_date_to_date(r[11]),  # znp_date
                )
            )

        cur.execute("TRUNCATE znp_data RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data
                (parent_id, plan_doc, payment_purpose,
                plan_payment_date, fact_payment_date, plan_sum,
                fact_sum, crc32_hash, stage, znp_igk, znp_payment_type,
                znp_status, znp_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            new_data,
        )

        relink_znp_parents()

        cur.execute("SELECT COUNT(*) FROM znp_data WHERE parent_id IS NULL")
        unmatched_count = cur.fetchone()[0]

    return f"обработано заявок: {len(new_data)}, без совпадения с договором: {unmatched_count}"


# --- Нормализация заявок SAP ---


def normalize_znp_sap():
    """Нормализует данные заявок SAP из staging_znp_sap_excel в znp_data_sap."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT igk, cfo, c_agent, reg_num, items, vv_sum,
                   bank_name, stage_e, stage_f, payment_possible,
                   init_payment_date, normalize_doc_num
            FROM staging_znp_sap_excel
            WHERE c_type = 'ГОЗ'
        """)
        staging_rows = cur.fetchall()

        new_data = []
        no_igk_count = 0
        for r in staging_rows:
            if r[0] is None:
                no_igk_count += 1
            new_data.append(r)

        cur.execute("TRUNCATE znp_data_sap RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data_sap
                (igk, cfo, c_agent, reg_num, items, vv_sum,
                 bank_name, stage_e, stage_f, payment_possible,
                 init_payment_date, normalize_doc_num)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
