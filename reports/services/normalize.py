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

TWO_PLACES = Decimal("0.01")
YEAR_COLS = [f"y{str(y)[2:]}" for y in YEARS]
STATUS_PLACEHOLDERS = ", ".join(["%s"] * len(CONCLUDED))

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


def to_decimal(value):
    if value is None:
        return None

    text = str(value).strip()
    if text in {"", "-", "None"}:
        return None

    try:
        cleaned = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def year_flags(god_igk):
    try:
        year = int(str(god_igk).strip()[:4])
    except (ValueError, TypeError):
        year = None

    return tuple(year == y for y in YEARS)


def norm(value):
    return str(value).strip() if value is not None else None


def plan_month(value):
    text = norm(value)
    if not text:
        return None

    parts = text.split(".")

    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}.{parts[1].zfill(2)}"

    if len(parts) == 2 and len(parts[0]) == 4:
        return f"{parts[0]}.{parts[1].zfill(2)}"

    return None


def values_equal(a, b):
    left = to_decimal(a)
    right = to_decimal(b)

    if left is None and right is None:
        return True

    if left is None or right is None:
        return False

    return left.quantize(TWO_PLACES) == right.quantize(TWO_PLACES)


def status_group(status):
    if status in CONCLUDED:
        return "concluded"

    if status in NOT_CONCL:
        return "not_concluded"

    return None


def _indexed_lookup(rows, key_fn, value_fn):
    counts = defaultdict(int)
    result = {}

    for row in rows:
        base_key = key_fn(row)
        index = counts[base_key]
        counts[base_key] += 1
        result[base_key + (index,)] = value_fn(row)

    return result


def text_ru_date_to_date(value):
    text = norm(value)
    if not text:
        return None

    parts = text.split()
    if len(parts) < 3:
        return None

    day_str, month_str, year_str = parts[:3]
    month = MONTH_MAP.get(month_str.rstrip("."))

    if month is None:
        return None

    day_digits = "".join(ch for ch in day_str if ch.isdigit())
    year_digits = "".join(ch for ch in year_str if ch.isdigit())

    if not day_digits or len(year_digits) < 4:
        return None

    try:
        return date(int(year_digits[:4]), month, int(day_digits))
    except ValueError:
        return None


def dot_date_to_date(value):
    text = norm(value)
    if not text:
        return None

    parts = text.split()
    if not parts:
        return None

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(parts[0], fmt).date()
        except ValueError:
            continue

    return None


def parse_date(value):
    result = dot_date_to_date(value)
    if result:
        return result

    return text_ru_date_to_date(value)


def normalize_contracts():
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
            y25, y26, y27 = year_flags(r[14])

            new_data.append(
                (
                    norm(r[0]),
                    norm(r[1]),
                    norm(r[2]),
                    norm(r[3]),
                    norm(r[4]),
                    norm(r[5]) or None,
                    norm(r[6]),
                    norm(r[7]),
                    to_decimal(r[8]),
                    to_decimal(r[9]),
                    to_decimal(r[10]),
                    norm(r[11]),
                    y25,
                    y26,
                    y27,
                    plan_month(r[12]),
                    norm(r[14]),
                    to_decimal(r[13]),
                    contract_hash(norm(r[0]), norm(r[1]), norm(r[3]), norm(r[11])),
                    to_decimal(r[15]),
                )
            )

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
                r[15] or "",
            ),
            value_fn=lambda r: r,
        )

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

        history = []

        for key, new_row in new_lookup.items():
            if key not in old_lookup:
                continue

            old_status, old_plan, old_fact, old_sum = old_lookup[key]
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
                    "".join(key[:-1]),
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

        cur.execute(
            "DELETE FROM contract_counts_snapshot WHERE upload_date = %s",
            [today],
        )

        for year_col in YEAR_COLS:
            cur.execute(
                f"""
                INSERT INTO contract_counts_snapshot
                    (upload_date, igk, cfo, year_col, concluded_count)
                SELECT %s, RIGHT(igk, 4), cfo, %s, COUNT(DISTINCT contract)
                FROM igk_stat_data
                WHERE {year_col}=TRUE
                  AND status IN ({STATUS_PLACEHOLDERS})
                  AND contract IS NOT NULL AND TRIM(contract) != ''
                  AND igk IS NOT NULL AND TRIM(igk) != ''
                  AND cfo IS NOT NULL AND TRIM(cfo) != ''
                GROUP BY RIGHT(igk, 4), cfo
                """,
                [today, year_col, *CONCLUDED],
            )

        relink_znp_parents()

    return f"обработано строк: {len(new_data)}, изменений записано: {len(history)}"


def normalize_znp():
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
                    None,
                    norm(r[1]),
                    norm(r[2]),
                    parse_date(r[3]),
                    parse_date(r[4]),
                    to_decimal(r[5]),
                    to_decimal(r[6]),
                    r[0],
                    norm(r[7]),
                    norm(r[8]),
                    norm(r[9]),
                    norm(r[10]),
                    parse_date(r[11]),
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

    return (
        f"обработано заявок: {len(new_data)}, "
        f"без совпадения с договором: {unmatched_count}"
    )


def normalize_znp_sap():
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT igk, cfo, c_agent, reg_num, items, vv_sum,
                   bank_name, stage_e, stage_f, stage_c, payment_possible,
                   normalize_doc_num, created_date
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
                 bank_name, stage_e, stage_f, stage_c, payment_possible,
                 normalize_doc_num, created_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
