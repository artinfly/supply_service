from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):

    def handle(self, *args, **kwargs):
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

        self.stdout.write(
            f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
        )
