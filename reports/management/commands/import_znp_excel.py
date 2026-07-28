import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from reports.services.hashing import contract_hash

COLUMN_MAP = {
    "ИГК договора": "igk",
    "ИГК заявки": "znp_igk",
    "Контрагент": "c_agent",
    "ДокументПланирования.Номер": "plan_doc",
    "Этап": "stage",
    "Назначение платежа": "payment_purpose",
    "Договор": "contract",
    "Прогнозная дата оплаты": "plan_payment_date",
    "Фактическая дата оплаты": "fact_payment_date",
    "Сумма руб планирования": "plan_sum",
    "Сумма руб оплаты": "fact_sum",
    "ТипПлатежа": "znp_payment_type",
}

_NORMALIZED_COLUMN_MAP = {
    name.strip().casefold(): field for name, field in COLUMN_MAP.items()
}

DB_FIELDS = list(COLUMN_MAP.values()) + ["crc32_hash"]
INSERT_SQL = (
    f"INSERT INTO staging_znp_excel ({', '.join(DB_FIELDS)}) "
    f"VALUES ({', '.join(['%s'] * len(DB_FIELDS))})"
)


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        filepath = options["filepath"]
        wb = None

        try:
            try:
                wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            except FileNotFoundError:
                raise CommandError(f"file not found: {filepath}")
            except Exception as exc:
                raise CommandError(str(exc))

            ws = wb.active
            rows = ws.iter_rows(min_row=6, values_only=True)

            try:
                header = next(rows)
            except StopIteration:
                raise CommandError("file is empty")

            col_map = {
                i: _NORMALIZED_COLUMN_MAP[str(cell).strip().casefold()]
                for i, cell in enumerate(header)
                if cell and str(cell).strip().casefold() in _NORMALIZED_COLUMN_MAP
            }

            if not col_map:
                raise CommandError("no matching columns found in header")

            missing_fields = set(COLUMN_MAP.values()) - set(col_map.values())
            if missing_fields:
                self.stdout.write(
                    self.style.WARNING(
                        f"columns not found in file, will stay empty: {', '.join(sorted(missing_fields))}"
                    )
                )

            data = []
            for row in rows:
                if not any(row):
                    continue
                record = dict.fromkeys(DB_FIELDS)
                for i, field in col_map.items():
                    if i < len(row) and row[i] is not None:
                        record[field] = str(row[i]).strip()
                record["crc32_hash"] = contract_hash(
                    record["igk"],
                    record["c_agent"],
                    record["contract"],
                    record["stage"],
                )
                data.append(tuple(record[f] for f in DB_FIELDS))

            wb.close()

            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("TRUNCATE staging_znp_excel RESTART IDENTITY")
                    if data:
                        cur.executemany(INSERT_SQL, data)

            self.stdout.write(f"loaded {len(data)} rows into staging_znp_excel")
        finally:
            if wb:
                wb.close()
