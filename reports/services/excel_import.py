# Общая часть чтения xlsx: открыть файл, найти колонки, залить в staging.
# Сами колонки перечислены в командах import_*.
import openpyxl
from django.core.management.base import CommandError
from django.db import connection, transaction


def open_sheet(filepath, header_row=1):
    try:
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    except FileNotFoundError:
        raise CommandError(f"файл не найден: {filepath}")
    except Exception as exc:
        raise CommandError(str(exc))
    return wb, wb.active.iter_rows(min_row=header_row, values_only=True)


def map_columns(rows, column_map, command, required=()):
    lookup = {name.strip().casefold(): field for name, field in column_map.items()}
    known = set(lookup)
    header = next(
        (r for r in rows if known & {str(c).strip().casefold() for c in r if c}), None
    )
    if header is None:
        raise CommandError("Документ не соответствует формату")
    positions = {
        i: lookup[str(cell).strip().casefold()]
        for i, cell in enumerate(header)
        if cell and str(cell).strip().casefold() in lookup
    }
    if not positions:
        raise CommandError("Документ не соответствует формату")

    missing = set(column_map.values()) - set(positions.values())
    if missing:
        raise CommandError("Документ не соответствует формату")
    return positions


def read_values(row, positions, fields, empty_as_null=False):
    record = dict.fromkeys(fields)
    for i, field in positions.items():
        if i < len(row) and row[i] is not None:
            value = str(row[i]).strip()
            record[field] = None if empty_as_null and value == "" else value
    return record


def replace_table(table, fields, data):
    insert_sql = (
        f"INSERT INTO {table} ({', '.join(fields)}) "
        f"VALUES ({', '.join(['%s'] * len(fields))})"
    )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY")
        if data:
            cur.executemany(insert_sql, data)
