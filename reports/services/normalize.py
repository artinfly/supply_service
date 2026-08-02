# Разбор загруженного файла: из staging_* в рабочие таблицы.
# Вызывается командами load_*, сама по себе не запускается.
from collections import defaultdict
from datetime import date

from django.db import connection, transaction

from reports.services.linking import contract_hash, relink_znp_parents
from reports.services.queries import ADVANCE, CONCLUDED, POSTPAYMENT, YEARS


def to_float(val):
    if not val or str(val).strip() in ("", "-", "None"):
        return None
    try:
        return float(str(val).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def year_flags(god_igk):
    try:
        y = int(str(god_igk).strip()[:4])
    except Exception:
        y = None
    return tuple(y == year for year in YEARS)


def norm(val):
    return str(val).strip() if val is not None else None


def plan_month(val):
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
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(float(a), 2) == round(float(b), 2)


CONCLUDED_SQL = ", ".join(f"'{s}'" for s in CONCLUDED)


YEAR_MAP = [(f"y{str(y)[2:]}", y) for y in YEARS]


def _indexed_lookup(rows, key_fn, value_fn):
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


def text_ru_date_to_date(val: str):
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


def normalize_contracts():
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            INSERT INTO nsi_cfo (cfo)
            SELECT DISTINCT TRIM(cfo) FROM staging_excel
            WHERE cfo IS NOT NULL AND TRIM(cfo) <> ''
            ON CONFLICT DO NOTHING
        """)

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
                   tol, etap_grafika, dataplan, summa_dogovora, god_igk
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
                    to_float(r[8]),
                    to_float(r[9]),
                    to_float(r[10]),
                    norm(r[11]),
                    y25,
                    y26,
                    y27,
                    False,
                    plan_month(r[12]),
                    norm(r[14]),
                    to_float(r[13]),
                    contract_hash(norm(r[0]), norm(r[1]), norm(r[3]), norm(r[11])),
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
                r[16] or "",
            ),
            value_fn=lambda r: (r[4], r[8], r[9], r[18]),
        )

        today = date.today()
        history = []
        for key, new_vals in new_lookup.items():
            if key not in old_lookup:
                continue
            old_vals = old_lookup[key]

            old_status, old_plan, old_fact, old_sum = old_vals
            new_status, new_plan, new_fact, new_sum = new_vals

            status_changed = old_status != new_status
            plan_changed = not floats_equal(old_plan, new_plan)
            fact_changed = not floats_equal(old_fact, new_fact)
            sum_changed = not floats_equal(old_sum, new_sum)

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
                 y25, y26, y27, is_deleted, plan_date, c_date, contract_sum,
                 crc32_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                znp_status
            FROM staging_znp_excel sze;
        """)
        staging_rows = cur.fetchall()

        new_data = []
        unmatched_count = 0
        for r in staging_rows:
            if r[0] is None:
                unmatched_count += 1
            new_data.append(
                (
                    r[0],
                    norm(r[1]),
                    norm(r[2]),
                    text_ru_date_to_date(norm(r[3])),
                    text_ru_date_to_date(norm(r[4])),
                    to_float(r[5]),
                    to_float(r[6]),
                    r[7],
                    norm(r[8]),
                    norm(r[9]),
                    norm(r[10]),
                    norm(r[11]),
                )
            )

        cur.execute("TRUNCATE znp_data RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data
                (parent_id, plan_doc, payment_purpose,
                plan_payment_date, fact_payment_date, plan_sum,
                fact_sum, crc32_hash, stage, znp_igk, znp_payment_type,
                znp_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без совпадения с договором: {unmatched_count}"


def normalize_znp_sap():
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
                normalize_doc_num
            FROM staging_znp_sap_excel szse
            WHERE c_type = 'ГОЗ';
        """)
        staging_rows = cur.fetchall()

        new_data = []
        no_igk_count = 0
        for r in staging_rows:
            if r[0] is None:
                no_igk_count += 1
            new_data.append(
                (
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    r[10],
                )
            )

        cur.execute("TRUNCATE znp_data_sap RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data_sap
                (igk, cfo, c_agent, reg_num,
                items, vv_sum, bank_name, stage_e, 
                stage_f, payment_possible, normalize_doc_num
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
