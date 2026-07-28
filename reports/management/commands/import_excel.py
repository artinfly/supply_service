import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

COLUMN_MAP = {
    "ИГК": "igk",
    "Контрагент": "kontragent",
    "ЦФО": "cfo",
    "Договор": "dogovor",
    "Состояние": "sostoyanie",
    "Тип платежа": "tip_platezha",
    "Предмет": "predmet",
    "Заказ": "zakaz",
    "ПЛАН": "plan",
    "ФАКТ": "fakt",
    "Тол": "tol",
    "Этап графика": "etap_grafika",
    "ДатаПЛАН": "dataplan",
    "Создан": "sozdan",
    "ГодИГК": "god_igk",
}

_NORMALIZED_COLUMN_MAP = {
    name.strip().casefold(): field for name, field in COLUMN_MAP.items()
}

DB_FIELDS = list(COLUMN_MAP.values())
# из этих колонок считается crc32_hash — ключ связки договоров с ЗНП;
# если хоть одной нет в файле, хеш посчитается от None и связь порвётся у всех
HASH_FIELDS = {"igk", "kontragent", "dogovor", "etap_grafika"}
INSERT_SQL = (
    f"INSERT INTO staging_excel ({', '.join(DB_FIELDS)}) "
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
            rows = ws.iter_rows(values_only=True)

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

            missing_fields = set(DB_FIELDS) - set(col_map.values())
            missing_hash_fields = missing_fields & HASH_FIELDS
            if missing_hash_fields:
                raise CommandError(
                    "missing columns required for crc32_hash (contract linking would "
                    f"silently fail for every row): {', '.join(sorted(missing_hash_fields))}"
                )
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
                data.append(tuple(record[f] for f in DB_FIELDS))

            wb.close()

            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("TRUNCATE staging_excel RESTART IDENTITY")
                    if data:
                        cur.executemany(INSERT_SQL, data)

            self.stdout.write(f"loaded {len(data)} rows into staging_excel")
        finally:
            if wb:
                wb.close()
