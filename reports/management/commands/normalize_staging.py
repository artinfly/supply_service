from django.core.management.base import BaseCommand
from django.db import connection


def to_float(val):
    if not val or str(val).strip() in ('', '-', 'None'):
        return None
    try:
        return float(str(val).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except ValueError:
        return None


def year_flags(dataplan):
    try:
        y = int(str(dataplan).strip()[:4])
        return y == 2025, y == 2026, y == 2027
    except Exception:
        return False, False, False


def norm(val):
    return str(val).strip() if val is not None else None


def floats_equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(float(a), 2) == round(float(b), 2)


class Command(BaseCommand):

    def handle(self, *args, **kwargs):
        with connection.cursor() as cur:

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
                       tol, etap_grafika, dataplan, sozdan
                FROM staging_excel
            """)
            staging_rows = cur.fetchall()

            new_data = []
            for r in staging_rows:
                y25, y26, y27 = year_flags(r[12])
                new_data.append((
                    norm(r[0]),  norm(r[1]),  norm(r[2]),  norm(r[3]),
                    norm(r[4]),  norm(r[5]) or None,
                    norm(r[6]),  norm(r[7]),
                    to_float(r[8]),  to_float(r[9]),  to_float(r[10]),
                    norm(r[11]), y25, y26, y27, False,
                    norm(r[12]), norm(r[13])
                ))

            cur.execute("""
                SELECT igk, c_agent, contract, item, "order", stage, plan_date,
                       status, plan, fact
                FROM igk_stat_data
            """)
            old_lookup = {
                (
                    norm(r[0]) or '', norm(r[1]) or '', norm(r[2]) or '',
                    norm(r[3]) or '', norm(r[4]) or '', norm(r[5]) or '',
                    norm(r[6]) or ''
                ): (r[7], r[8], r[9])
                for r in cur.fetchall()
            }

            new_lookup = {
                (
                    r[0] or '', r[1] or '', r[3] or '',
                    r[6] or '', r[7] or '', r[11] or '',
                    r[16] or ''
                ): (r[4], r[8], r[9])
                for r in new_data
            }

            today = __import__('datetime').date.today()
            history = []
            for key, new_vals in new_lookup.items():
                if key not in old_lookup:
                    continue
                old_vals = old_lookup[key]

                old_status, old_plan, old_fact = old_vals
                new_status, new_plan, new_fact = new_vals

                status_changed = old_status != new_status
                plan_changed   = not floats_equal(old_plan, new_plan)
                fact_changed   = not floats_equal(old_fact, new_fact)

                if not (status_changed or plan_changed or fact_changed):
                    continue

                history.append((
                    ''.join(key),
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
                ))

            if history:
                cur.executemany("""
                    INSERT INTO contracts_history
                        (hash, old_status, new_status,
                        update_date, upload_date,
                        old_plan, new_plan,
                        old_fact, new_fact,
                        plan_changed_date, fact_changed_date)
                    VALUES (digest(%s, 'md5'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, history)

            cur.execute('TRUNCATE igk_stat_data RESTART IDENTITY')
            cur.executemany("""
                INSERT INTO igk_stat_data
                    (igk, c_agent, cfo, contract, status, payment_type,
                     item, "order", plan, fact, tolerance, stage,
                     y25, y26, y27, is_deleted, plan_date, c_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, new_data)

        self.stdout.write(f'done: {len(new_data)} rows, {len(history)} changes')