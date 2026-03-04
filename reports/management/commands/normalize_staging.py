"""
python manage.py normalize_staging

Переносит данные из staging_excel → igk_stat_data, nsi_igk, nsi_cfo.
Полностью заменяет igk_stat_data при каждом запуске (TRUNCATE + INSERT),
чтобы данные всегда соответствовали последнему загруженному файлу.
"""

from django.core.management.base import BaseCommand
from django.db import connection


# ─────────────────────────────────────────────
# Точные статусы из Excel (регистр важен!)
# Если в вашем Excel другие — поправьте здесь.
# ─────────────────────────────────────────────
CONCLUDED_STATUSES = ('Исполнен', 'Исполняется', 'Заключен')
NOT_CONCLUDED_STATUS = 'Не заключен'
TERMINATED_STATUS = 'Расторгнут'
ADVANCE_PAYMENT = 'Аванс'


def parse_float(val: str | None) -> float | None:
    """'1 239 587,32' → 1239587.32"""
    if not val or str(val).strip() in ('', '-', 'None'):
        return None
    try:
        return float(str(val).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except ValueError:
        return None


def parse_year_flags(dataplan: str | None) -> tuple[bool, bool, bool]:
    """'2025.04' → (True, False, False)"""
    if not dataplan or str(dataplan).strip() == '':
        return False, False, False
    try:
        year = int(str(dataplan).strip()[:4])
        return year == 2025, year == 2026, year == 2027
    except (ValueError, IndexError):
        return False, False, False


class Command(BaseCommand):
    help = 'Нормализует данные из staging_excel в основные таблицы'

    def handle(self, *args, **kwargs):
        with connection.cursor() as cur:

            # ── 1. Справочник ЦФО ──────────────────────────────────────
            self.stdout.write('Заполняем nsi_cfo...')
            cur.execute("""
                INSERT INTO dbo.nsi_cfo (cfo)
                SELECT DISTINCT TRIM(cfo)
                FROM dbo.staging_excel
                WHERE cfo IS NOT NULL AND TRIM(cfo) <> ''
                ON CONFLICT (cfo) DO NOTHING
            """)

            # ── 2. Справочник ИГК ──────────────────────────────────────
            self.stdout.write('Заполняем nsi_igk...')
            cur.execute("""
                INSERT INTO dbo.nsi_igk (igk)
                SELECT DISTINCT TRIM(igk)
                FROM dbo.staging_excel
                WHERE igk IS NOT NULL AND TRIM(igk) <> ''
                ON CONFLICT (igk) DO NOTHING
            """)

            # ── 3. Читаем staging ───────────────────────────────────────
            self.stdout.write('Читаем staging_excel...')
            cur.execute("""
                SELECT
                    igk, kontragent, cfo, dogovor, sostoyanie,
                    tip_platezha, predmet, zakaz, plan, fakt,
                    tol, etap_grafika, dataplan, sozdan
                FROM dbo.staging_excel
            """)
            rows = cur.fetchall()
            self.stdout.write(f'  Строк в staging: {len(rows)}')

            # ── 4. Формируем записи для igk_stat_data ──────────────────
            records = []
            for row in rows:
                (igk, c_agent, cfo, contract, status,
                 payment_type, item, order_, plan_raw, fact_raw,
                 tol_raw, stage, dataplan, c_date) = row

                plan_val = parse_float(plan_raw)
                fact_val = parse_float(fact_raw)
                tol_val  = parse_float(tol_raw)
                y25, y26, y27 = parse_year_flags(dataplan)

                # Нормализуем payment_type: пустое → None
                pt = str(payment_type).strip() if payment_type else None
                if pt == '':
                    pt = None

                records.append((
                    str(igk).strip()       if igk       else None,
                    str(c_agent).strip()   if c_agent   else None,
                    str(cfo).strip()       if cfo       else None,
                    str(contract).strip()  if contract  else None,
                    str(status).strip()    if status    else None,
                    pt,
                    str(item).strip()      if item      else None,
                    str(order_).strip()    if order_    else None,
                    plan_val,
                    fact_val,
                    tol_val,
                    str(stage).strip()     if stage     else None,
                    y25, y26, y27,
                    False,                  # is_deleted
                    str(dataplan).strip()  if dataplan  else None,
                    str(c_date).strip()    if c_date    else None,
                ))

            # ── 5. Заменяем igk_stat_data ──────────────────────────────
            self.stdout.write('Очищаем igk_stat_data...')
            cur.execute('TRUNCATE TABLE dbo.igk_stat_data RESTART IDENTITY')

            self.stdout.write(f'Вставляем {len(records)} записей...')
            cur.executemany("""
                INSERT INTO dbo.igk_stat_data
                    (igk, c_agent, cfo, contract, status, payment_type,
                     item, "order", plan, fact, tolerance, stage,
                     y25, y26, y27, is_deleted, plan_date, c_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, records)

        self.stdout.write(self.style.SUCCESS(
            f'✓ Нормализация завершена. Вставлено {len(records)} записей.'
        ))