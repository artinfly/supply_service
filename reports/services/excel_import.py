import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from .hashing import contract_hash


class ExcelImportCommand(BaseCommand):
    table = ""
    column_map = {}
    header_row = 1
    required_columns = ()
    hash_fields = ()
    skip_if_blank = None
    empty_as_null = False

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    @property
    def db_fields(self):
        fields = list(self.column_map.values())
        if self.hash_fields:
            fields.append("crc32_hash")
        return fields

    def _open(self, filepath):
        try:
            return openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        except FileNotFoundError:
            raise CommandError(f"file not found: {filepath}")
        except Exception as exc:
            raise CommandError(str(exc))

    def _column_positions(self, header):
        lookup = {
            name.strip().casefold(): field for name, field in self.column_map.items()
        }
        positions = {
            i: lookup[str(cell).strip().casefold()]
            for i, cell in enumerate(header)
            if cell and str(cell).strip().casefold() in lookup
        }
        if not positions:
            raise CommandError("no matching columns found in header")

        missing = set(self.column_map.values()) - set(positions.values())
        blocking = missing & set(self.required_columns)
        if blocking:
            raise CommandError(
                "missing columns required for crc32_hash (contract linking would "
                f"silently fail for every row): {', '.join(sorted(blocking))}"
            )
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    "columns not found in file, will stay empty: "
                    f"{', '.join(sorted(missing))}"
                )
            )
        return positions

    def _read_row(self, row, positions):
        record = dict.fromkeys(self.db_fields)
        for i, field in positions.items():
            if i < len(row) and row[i] is not None:
                value = str(row[i]).strip()
                record[field] = None if self.empty_as_null and value == "" else value
        if self.hash_fields:
            record["crc32_hash"] = contract_hash(*(record[f] for f in self.hash_fields))
        return tuple(record[f] for f in self.db_fields)

    def handle(self, *args, **options):
        wb = self._open(options["filepath"])
        try:
            rows = wb.active.iter_rows(min_row=self.header_row, values_only=True)
            try:
                header = next(rows)
            except StopIteration:
                raise CommandError("file is empty")

            positions = self._column_positions(header)
            data = [
                self._read_row(row, positions)
                for row in rows
                if any(row)
                and not (
                    self.skip_if_blank is not None
                    and len(row) > self.skip_if_blank
                    and row[self.skip_if_blank] == ""
                )
            ]
        finally:
            wb.close()

        fields = self.db_fields
        insert_sql = (
            f"INSERT INTO {self.table} ({', '.join(fields)}) "
            f"VALUES ({', '.join(['%s'] * len(fields))})"
        )
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"TRUNCATE {self.table} RESTART IDENTITY")
            if data:
                cur.executemany(insert_sql, data)

        self.stdout.write(f"loaded {len(data)} rows into {self.table}")
