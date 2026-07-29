from datetime import date

from django.core.management.base import BaseCommand
from django.db import connection, transaction

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


def to_float(val):
    if not val or str(val).strip() in ("", "-", "None"):
        return None
    try:
        return float(str(val).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def norm(val):
    return str(val).strip() if val is not None else None


class Command(BaseCommand):

    def handle(self, *args, **kwargs):
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
                    znp_payment_type
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
                    )
                )

            cur.execute("TRUNCATE znp_data RESTART IDENTITY")
            cur.executemany(
                """
                INSERT INTO znp_data
                    (parent_id, plan_doc, payment_purpose,
                    plan_payment_date, fact_payment_date, plan_sum,
                    fact_sum, crc32_hash, stage, znp_igk, znp_payment_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
                new_data,
            )

        self.stdout.write(
            f"done: {len(new_data)} rows, {unmatched_count} without a matching contract"
        )
