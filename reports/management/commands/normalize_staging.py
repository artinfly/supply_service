from django.core.management.base import BaseCommand
from django.db import connection
from datetime import date

def parse_float(val):
    if not val or str(val).strip() in ('', '-', 'None'):
        return None
    try:
        return float(str(val).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except ValueError:
        return None

def parse_year_flags(dataplan):
    if not dataplan or str(dataplan).strip() == '':
        return False, False, False
    try:
        year = int(str(dataplan).strip()[:4])
        return year == 2025, year == 2026, year == 2027
    except (ValueError, IndexError):
        return False, False, False

class Command(BaseCommand):
    help = 'normalize_staging'

    def handle(self, *args, **kwargs):
        today = date.today()

        with connection.cursor() as cur:
            cur.execute("""
                INSERT INTO nsi_cfo (cfo)
                SELECT DISTINCT TRIM(cfo)
                FROM staging_excel
                WHERE cfo IS NOT NULL AND TRIM(cfo) <> ''
                ON CONFLICT (cfo) DO NOTHING
            """)

            cur.execute("""
                INSERT INTO nsi_igk (igk)
                SELECT DISTINCT TRIM(igk)
                FROM staging_excel
                WHERE igk IS NOT NULL AND TRIM(igk) <> ''
                ON CONFLICT (igk) DO NOTHING
            """)

            cur.execute("""
                SELECT igk, kontragent, cfo, dogovor, sostoyanie,
                    tip_platezha, predmet, zakaz, plan, fakt,
                    tol, etap_grafika, dataplan, sozdan
                FROM staging_excel
            """)
            rows = cur.fetchall()

            new_records = []
            for row in rows:
                (igk, c_agent, cfo, contract, status,
                 payment_type, item, order_, plan_raw, fact_raw,
                 tol_raw, stage, dataplan, c_date) = row

                plan_val = parse_float(plan_raw)
                fact_val = parse_float(fact_raw)
                tol_val = parse_float(tol_raw)
                y25, y26, y27 = parse_year_flags(dataplan)

                pt = str(payment_type).strip() if payment_type else None
                if pt == '':
                    pt = None

                new_records.append((
                    str(igk).strip() if igk else None,
                    str(c_agent).strip() if c_agent else None,
                    str(cfo).strip() if cfo else None,
                    str(contract).strip() if contract else None,
                    str(status).strip() if status else None,
                    pt,
                    str(item).strip() if item else None,
                    str(order_).strip() if order_ else None,
                    plan_val, fact_val, tol_val,
                    str(stage).strip() if stage else None,
                    y25, y26, y27,
                    False,
                    str(dataplan).strip() if dataplan else None,
                    str(c_date).strip() if c_date else None,
                ))

            cur.execute("""
                SELECT igk, c_agent, contract, item, "order", stage, plan_date,
                    status, plan, fact
                FROM igk_stat_data
            """)
            old_rows = cur.fetchall()

            old_map = {}
            for r in old_rows:
                key = (
                    str(r[0] or ''), str(r[1] or ''), str(r[2] or ''),
                    str(r[3] or ''), str(r[4] or ''), str(r[5] or '').strip(),
                    str(r[6] or '')
                )
                old_map[key] = {'status': r[7], 'plan': r[8], 'fact': r[9]}

            new_map = {}
            for r in new_records:
                key = (
                    str(r[0] or ''), str(r[1] or ''), str(r[3] or ''),
                    str(r[6] or ''), str(r[7] or ''), str(r[11] or '').strip(),
                    str(r[16] or '')
                )
                new_map[key] = {'status': r[4], 'plan': r[8], 'fact': r[9]}

            history_records = []
            for key, new_vals in new_map.items():
                if key not in old_map:
                    continue
                old_vals = old_map[key]
                igk, c_agent, contract, item, order_, stage, plan_date = key
                hash_str = f"{igk}{c_agent}{contract}{item}{order_}{stage}{plan_date}"

                old_status = old_vals['status']
                new_status = new_vals['status']
                old_plan = old_vals['plan']
                new_plan = new_vals['plan']
                old_fact = old_vals['fact']
                new_fact = new_vals['fact']

                status_changed = old_status != new_status
                plan_changed = old_plan != new_plan and not (old_plan is None and new_plan is None)
                fact_changed = old_fact != new_fact and not (old_fact is None and new_fact is None)

                if status_changed or plan_changed or fact_changed:
                    history_records.append((
                        hash_str,
                        old_status if status_changed else None,
                        new_status if status_changed else None,
                        today if status_changed else None,
                        today,
                        old_plan if plan_changed else None,
                        new_plan if plan_changed else None,
                        old_fact if fact_changed else None,
                        new_fact if fact_changed else None,
                        today if plan_changed else None,
                        today if fact_changed else None,
                    ))

            if history_records:
                cur.executemany("""
                    INSERT INTO contracts_history
                        (hash, old_status, new_status, update_date, upload_date,
                         old_plan, new_plan, old_fact, new_fact,
                         plan_changed_date, fact_changed_date)
                    VALUES (digest(%s, 'md5'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, history_records)

            cur.execute('TRUNCATE TABLE igk_stat_data RESTART IDENTITY')

            cur.executemany("""
                INSERT INTO igk_stat_data
                    (igk, c_agent, cfo, contract, status, payment_type,
                     item, "order", plan, fact, tolerance, stage,
                     y25, y26, y27, is_deleted, plan_date, c_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, new_records)

        self.stdout.write(f'done: {len(new_records)} rows, {len(history_records)} changes')
