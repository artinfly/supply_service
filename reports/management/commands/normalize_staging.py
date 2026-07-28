from collections import defaultdict
from datetime import date

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from reports.services.hashing import contract_hash
from reports.services.queries import CONCLUDED, YEARS
from reports.services.znp_linking import relink_znp_parents


def to_float(val):
    if not val or str(val).strip() in ("", "-", "None"):
        return None
    try:
        return float(str(val).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def year_flags(god_igk):
    # длина кортежа обязана совпадать с числом y-полей на IgkStatData
    try:
        y = int(str(god_igk).strip()[:4])
    except Exception:
        y = None
    return tuple(y == year for year in YEARS)


def norm(val):
    return str(val).strip() if val is not None else None


def floats_equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(float(a), 2) == round(float(b), 2)


CONCLUDED_SQL = ", ".join(f"'{s}'" for s in CONCLUDED)
YEAR_MAP = [(f"y{str(y)[2:]}", y) for y in YEARS]


def _indexed_lookup(rows, key_fn, value_fn):
    # источник шлёт полные дубли строк без ID: номер повтора в ключе не даёт
    # им схлопнуться и потерять изменения
    counts = defaultdict(int)
    result = {}
    for r in rows:
        base_key = key_fn(r)
        idx = counts[base_key]
        counts[base_key] += 1
        result[base_key + (idx,)] = value_fn(r)
    return result


class Command(BaseCommand):

    def handle(self, *args, **kwargs):
        # между TRUNCATE и вставкой база неконсистентна — только одной транзакцией
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

            cur.execute("""
                SELECT igk, kontragent, cfo, dogovor, sostoyanie,
                       tip_platezha, predmet, zakaz, plan, fakt,
                       tol, etap_grafika, dataplan, sozdan, god_igk
                FROM staging_excel
                WHERE tip_platezha IN ('Аванс', 'Постоплата')
            """)
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
                        norm(r[12]),
                        norm(r[14]),
                        contract_hash(norm(r[0]), norm(r[1]), norm(r[3]), norm(r[11])),
                    )
                )

            cur.execute("""
                SELECT igk, c_agent, contract, item, "order", stage, plan_date,
                       status, plan, fact
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
                value_fn=lambda r: (r[7], r[8], r[9]),
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
                value_fn=lambda r: (r[4], r[8], r[9]),
            )

            today = date.today()
            history = []
            for key, new_vals in new_lookup.items():
                if key not in old_lookup:
                    continue
                old_vals = old_lookup[key]

                old_status, old_plan, old_fact = old_vals
                new_status, new_plan, new_fact = new_vals

                status_changed = old_status != new_status
                plan_changed = not floats_equal(old_plan, new_plan)
                fact_changed = not floats_equal(old_fact, new_fact)

                if not (status_changed or plan_changed or fact_changed):
                    continue

                history.append(
                    (
                        # без номера повтора: хеш должен совпасть с digest()
                        # из queries.py::_HISTORY_JOIN
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
                        plan_changed_date, fact_changed_date)
                    VALUES (digest(%s, 'md5'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    history,
                )

            # без CASCADE: он вычистил бы znp_data вместе с договорами
            cur.execute("TRUNCATE igk_stat_data RESTART IDENTITY")
            cur.executemany(
                """
                INSERT INTO igk_stat_data
                    (igk, c_agent, cfo, contract, status, payment_type,
                     item, "order", plan, fact, tolerance, stage,
                     y25, y26, y27, is_deleted, plan_date, c_date, crc32_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
                new_data,
            )

            # иначе повторная загрузка за тот же день дублирует снимок
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

            # обязательно: TRUNCATE сбросил pp_id, и без пересборки связи ЗНП
            # молча окажутся привязаны к чужим договорам
            relink_znp_parents()

        self.stdout.write(f"done: {len(new_data)} rows, {len(history)} changes")
