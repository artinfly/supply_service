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
    try:
        header = next(rows)
    except StopIteration:
        raise CommandError("файл пустой")

    lookup = {name.strip().casefold(): field for name, field in column_map.items()}
    positions = {
        i: lookup[str(cell).strip().casefold()]
        for i, cell in enumerate(header)
        if cell and str(cell).strip().casefold() in lookup
    }
    if not positions:
        raise CommandError("в строке заголовка не найдено ни одной известной колонки")

    missing = set(column_map.values()) - set(positions.values())
    if missing:
        names = sorted(n for n, f in column_map.items() if f in missing)
        raise CommandError("в файле нет обязательных колонок: " + ", ".join(names))
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
