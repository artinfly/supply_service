"""
Модуль нормализации данных из staging-таблиц в рабочие.
Выполняет:
- перенос договоров (igk_stat_data) с вычислением истории изменений
- перенос заявок ФЗД (znp_data) с привязкой к договорам по crc32_hash
- перенос заявок SAP (znp_data_sap)
- обновление снимков количества договоров (contract_counts_snapshot)
- перепривязку заявок к договорам после загрузки
"""

from collections import defaultdict
from datetime import date, datetime

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


def to_float(val):
    """Преобразует строку в число с плавающей точкой, обрабатывая разделители."""
    if val is None or str(val).strip() in ("", "-", "None"):
        return None
    try:
        return float(str(val).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def year_flags(god_igk):
    """
    Преобразует строку 'ГодИГК' в кортеж булевых флагов для каждого года из YEARS.
    """
    try:
        y = int(str(god_igk).strip()[:4])
    except Exception:
        y = None
    return tuple(y == year for year in YEARS)


def norm(val):
    """Приводит значение к строке с удалением пробелов по краям, либо None."""
    return str(val).strip() if val is not None else None


def plan_month(val):
    """
    Извлекает месяц и год из строки вида 'день.месяц.год' или 'год.месяц'.
    Возвращает 'YYYY.MM' для использования в поле plan_date.
    """
    text = norm(val)
    if not text:
        return None
    parts = text.split(".")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}.{parts[1].zfill(2)}"
    if len(parts) == 2 and len(parts[0]) == 4:
        return f"{parts[0]}.{parts[1].zfill(2)}"
    return None


def floats_equal(a, b):
    """Сравнивает два числа с точностью до 2 знаков, учитывая None."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(float(a), 2) == round(float(b), 2)


CONCLUDED_SQL = ", ".join(f"'{s}'" for s in CONCLUDED)
YEAR_MAP = [(f"y{str(y)[2:]}", y) for y in YEARS]


def status_group(status):
    """Определяет группу статуса: 'concluded', 'not_concluded' или None."""
    if status in CONCLUDED:
        return "concluded"
    if status in NOT_CONCL:
        return "not_concluded"
    return None


def _indexed_lookup(rows, key_fn, value_fn):
    """
    Строит словарь для поиска по составному ключу.
    Если ключи повторяются, добавляет индекс повторения (для обработки дубликатов).
    """
    counts = defaultdict(int)
    result = {}
    for r in rows:
        base_key = key_fn(r)
        idx = counts[base_key]
        counts[base_key] += 1
        result[base_key + (idx,)] = value_fn(r)
    return result


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


def parse_date_ru(text):
    """
    Парсит дату в формате "день месяц_рус год" (например, "15 января 2023").
    Возвращает объект date или None.
    """
    if not text:
        return None
    parts = str(text).split()
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


def parse_date_dot(text):
    """
    Парсит дату в формате "dd.mm.yyyy" или "yyyy-mm-dd".
    Возвращает объект date или None.
    """
    if not text:
        return None
    parts = str(text).strip().split()
    if not parts:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(parts[0], fmt).date()
        except ValueError:
            continue
    return None


def parse_date_any(val):
    """
    Универсальный парсер даты: пробует оба формата (русский словесный и точечный).
    """
    if val is None:
        return None
    d = parse_date_ru(val)
    if d is not None:
        return d
    return parse_date_dot(val)


def normalize_contracts():
    """
    Переносит данные из staging_excel в igk_stat_data.
    Вычисляет историю изменений (contracts_history) и снимки количества договоров.
    Выполняется в одной транзакции.

    ВНИМАНИЕ: Индексы в new_data зависят от длины YEARS!
    Если добавляется новый год, нужно пересчитать все индексы.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            INSERT INTO nsi_igk (igk)
            SELECT DISTINCT TRIM(igk) FROM staging_excel
            WHERE igk IS NOT NULL AND TRIM(igk) <> ''
            ON CONFLICT DO NOTHING
        """)

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
            year_flags_tuple = year_flags(r[14])
            # ВАЖНО: индексы зависят от len(year_flags_tuple)!
            # Текущая структура (при YEARS = [2025, 2026, 2027]):
            # 0-11: основные поля, 12-14: year flags, 15: plan_date, 16: c_date,
            # 17: contract_sum, 18: crc32_hash, 19: remainder
            new_data.append(
                [
                    norm(r[0]),  # 0: igk
                    norm(r[1]),  # 1: c_agent
                    norm(r[2]),  # 2: cfo
                    norm(r[3]),  # 3: contract
                    norm(r[4]),  # 4: status
                    norm(r[5]) or None,  # 5: payment_type
                    norm(r[6]),  # 6: item
                    norm(r[7]),  # 7: order
                    to_float(r[8]),  # 8: plan
                    to_float(r[9]),  # 9: fact
                    to_float(r[10]),  # 10: tolerance
                    norm(r[11]),  # 11: stage
                    *year_flags_tuple,  # 12-14: y25, y26, y27 (длина = len(YEARS))
                    plan_month(r[12]),  # 15: plan_date
                    norm(r[14]),  # 16: c_date
                    to_float(r[13]),  # 17: contract_sum
                    None,  # 18: crc32_hash (заполним ниже)
                    to_float(r[15]),  # 19: remainder
                ]
            )

        # Вычисляем crc32_hash (используем отрицательный индекс для устойчивости)
        for row in new_data:
            row[-2] = contract_hash(row[0], row[1], row[3], row[11])

        today = timezone.localdate()

        # Загружаем старые данные для сравнения
        cur.execute("""
            SELECT igk, c_agent, contract, item, "order", stage, plan_date,
                   status, plan, fact, contract_sum
            FROM igk_stat_data
            ORDER BY pp_id
        """)
        old_rows = cur.fetchall()
        old_lookup = _indexed_lookup(
            old_rows,
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

        # Индексы для new_lookup (зависят от len(YEARS)!)
        # plan_date находится по индексу 12 + len(YEARS)
        plan_date_idx = 12 + len(YEARS)
        contract_sum_idx = 13 + len(YEARS)

        new_lookup = _indexed_lookup(
            new_data,
            key_fn=lambda r: (
                r[0] or "",
                r[1] or "",
                r[3] or "",
                r[6] or "",
                r[7] or "",
                r[11] or "",
                r[plan_date_idx] or "",
            ),
            value_fn=lambda r: r,
        )

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
                        row[0],  # igk
                        row[2],  # cfo
                        row[1],  # c_agent
                        row[3],  # contract
                        row[6],  # item
                        row[7],  # order
                        row[11],  # stage
                        row[plan_date_idx],  # plan_date
                        row[4],  # status
                        row[8],  # plan
                        row[contract_sum_idx],  # contract_sum
                    )
                )
        if appeared:
            cur.executemany(
                """
                INSERT INTO contracts_appeared
                (upload_date, kind, reason, igk, cfo, c_agent, contract, item, order_num, stage, plan_date, status, plan, contract_sum)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
                appeared,
            )

        history = []
        for key, new_row in new_lookup.items():
            if key not in old_lookup:
                continue
            old_vals = old_lookup[key]
            old_status, old_plan, old_fact, old_sum = old_vals
            new_status, new_plan, new_fact, new_sum = (
                new_row[4],
                new_row[8],
                new_row[9],
                new_row[contract_sum_idx],
            )

            status_changed = old_status != new_status
            plan_changed = not floats_equal(old_plan, new_plan)
            fact_changed = not floats_equal(old_fact, new_fact)
            sum_changed = not floats_equal(old_sum, new_sum)

            if not (status_changed or plan_changed or fact_changed or sum_changed):
                continue

            key_str = "".join(key[:-1])
            history.append(
                (
                    key_str,
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

        cur.execute("TRUNCATE igk_stat_data RESTART IDENTITY")
        year_fields = [f"y{str(y)[2:]}" for y in YEARS]
        insert_fields = [
            "igk",
            "c_agent",
            "cfo",
            "contract",
            "status",
            "payment_type",
            "item",
            '"order"',
            "plan",
            "fact",
            "tolerance",
            "stage",
            *year_fields,
            "plan_date",
            "c_date",
            "contract_sum",
            "crc32_hash",
            "remainder",
        ]
        placeholders = ", ".join(["%s"] * len(insert_fields))
        cur.executemany(
            f"""
            INSERT INTO igk_stat_data
                ({', '.join(insert_fields)})
            VALUES ({placeholders})
        """,
            new_data,
        )

        cur.execute(
            "DELETE FROM contract_counts_snapshot WHERE upload_date = %s", [today]
        )
        for year_col, year_val in YEAR_MAP:
            cur.execute(
                f"""
                INSERT INTO contract_counts_snapshot (upload_date, igk, cfo, year_col, concluded_count)
                SELECT
                    %s,
                    RIGHT(igk, 4),
                    cfo,
                    %s,
                    COUNT(DISTINCT contract)
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

        relink_znp_parents()

    return f"обработано строк: {len(new_data)}, изменений записано: {len(history)}"


def normalize_znp():
    """
    Переносит данные из staging_znp_excel в znp_data.
    Выполняет привязку к договорам по crc32_hash.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT
                (SELECT MIN(pp_id) FROM igk_stat_data isd WHERE isd.crc32_hash = sze.crc32_hash),
                plan_doc,
                payment_purpose,
                plan_payment_date,
                fact_payment_date,
                plan_sum,
                fact_sum,
                crc32_hash,
                stage,
                znp_igk,
                znp_payment_type,
                znp_status,
                znp_date
            FROM staging_znp_excel sze;
        """)
        staging_rows = cur.fetchall()

        new_data = []
        unmatched_count = 0
        for r in staging_rows:
            if r[0] is None:
                unmatched_count += 1
            plan_date = parse_date_any(r[3])
            fact_date = parse_date_any(r[4])
            znp_date = parse_date_any(r[12])
            new_data.append(
                (
                    r[0],
                    norm(r[1]),
                    norm(r[2]),
                    plan_date,
                    fact_date,
                    to_float(r[5]),
                    to_float(r[6]),
                    r[7],
                    norm(r[8]),
                    norm(r[9]),
                    norm(r[10]),
                    norm(r[11]),
                    znp_date,
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

    return f"обработано заявок: {len(new_data)}, без совпадения с договором: {unmatched_count}"


def normalize_znp_sap():
    """
    Переносит данные из staging_znp_sap_excel в znp_data_sap.
    Загружаются все строки (фильтр по c_type убран, чтобы не терять данные).

    ИСПРАВЛЕНО: Добавлен парсинг дат через parse_date_any() для всех DateField полей.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT
                igk,
                cfo,
                c_agent,
                reg_num,
                items,
                vv_sum,
                bank_name,
                stage_e,
                stage_f,
                payment_possible,
                init_payment_date,
                normalize_doc_num
            FROM staging_znp_sap_excel
        """)
        staging_rows = cur.fetchall()

        new_data = []
        no_igk_count = 0
        for r in staging_rows:
            if r[0] is None or str(r[0]).strip() == "":
                no_igk_count += 1
            # ИСПРАВЛЕНО: Парсим все даты через parse_date_any()
            new_data.append(
                (
                    r[0],  # igk
                    r[1],  # cfo
                    r[2],  # c_agent
                    r[3],  # reg_num
                    r[4],  # items
                    r[5],  # vv_sum
                    r[6],  # bank_name
                    parse_date_any(r[7]),  # stage_e (ИСПРАВЛЕНО)
                    parse_date_any(r[8]),  # stage_f (ИСПРАВЛЕНО)
                    parse_date_any(r[9]),  # payment_possible (ИСПРАВЛЕНО)
                    parse_date_any(r[10]),  # init_payment_date (ИСПРАВЛЕНО)
                    r[11],  # normalize_doc_num
                )
            )

        cur.execute("TRUNCATE znp_data_sap RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data_sap
                (igk, cfo, c_agent, reg_num,
                items, vv_sum, bank_name, stage_e, 
                stage_f, payment_possible, init_payment_date, normalize_doc_num)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
