from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Перенос данных из staging_excel в справочники и igk_stat_data с заполнением y25, y26, y27'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # 1. Заполнение справочника nsi_cfo
            cursor.execute("""
                INSERT INTO "dbo"."nsi_cfo" (cfo)
                SELECT DISTINCT cfo FROM "dbo"."staging_excel" WHERE cfo IS NOT NULL AND cfo != ''
                ON CONFLICT (cfo) DO NOTHING;
            """)
            self.stdout.write('Справочник nsi_cfo обновлён')

            # 2. Заполнение справочника nsi_igk
            cursor.execute("""
                INSERT INTO "dbo"."nsi_igk" (igk)
                SELECT DISTINCT igk FROM "dbo"."staging_excel" WHERE igk IS NOT NULL AND igk != ''
                ON CONFLICT (igk) DO NOTHING;
            """)
            self.stdout.write('Справочник nsi_igk обновлён')

            # 3. Перенос в igk_stat_data с вычислением y25, y26, y27 из dataplan (первые 4 символа)
            insert_sql = """
                INSERT INTO "dbo"."igk_stat_data" (
                    igk, c_agent, cfo, contract, status, payment_type,
                    item, "order", plan, fact, tolerance, stage,
                    plan_date, c_date, is_deleted,
                    y25, y26, y27
                )
                SELECT
                    s.igk,
                    s.kontragent,
                    s.cfo,
                    s.dogovor,
                    s.sostoyanie,
                    s.tip_platezha,
                    s.predmet,
                    s.zakaz,
                    NULLIF(replace(s.plan, ',', '.'), '')::float,
                    NULLIF(replace(s.fakt, ',', '.'), '')::float,
                    NULLIF(replace(s.tol, ',', '.'), '')::float,
                    s.etap_grafika,
                    s.dataplan,
                    s.sozdan,
                    FALSE,
                    CASE WHEN LEFT(s.dataplan, 4) = '2025' THEN TRUE ELSE FALSE END,
                    CASE WHEN LEFT(s.dataplan, 4) = '2026' THEN TRUE ELSE FALSE END,
                    CASE WHEN LEFT(s.dataplan, 4) = '2027' THEN TRUE ELSE FALSE END
                FROM "dbo"."staging_excel" s
                WHERE NOT EXISTS (
                    SELECT 1 FROM "dbo"."igk_stat_data" t
                    WHERE t.igk = s.igk 
                      AND t.c_agent = s.kontragent
                      AND t.contract = s.dogovor 
                      AND t.item = s.predmet
                )
            """
            cursor.execute(insert_sql)
            inserted = cursor.rowcount
            self.stdout.write(self.style.SUCCESS(f'В igk_stat_data добавлено {inserted} новых строк'))

            # 4. (Опционально) очистка staging-таблицы
            # cursor.execute("TRUNCATE TABLE dbo.staging_excel RESTART IDENTITY;")
            # self.stdout.write('staging_excel очищена')