from django.core.management.base import BaseCommand, CommandError
from django.db import connection
import openpyxl

COLUMN_MAP = {
    'ИГК':          'igk',
    'Контрагент':   'kontragent',
    'ЦФО':          'cfo',
    'Договор':      'dogovor',
    'Состояние':    'sostoyanie',
    'Тип платежа':  'tip_platezha',
    'Предмет':      'predmet',
    'Заказ':        'zakaz',
    'ПЛАН':         'plan',
    'ФАКТ':         'fakt',
    'Тол':          'tol',
    'Этап графика': 'etap_grafika',
    'ДатаПЛАН':     'dataplan',
    'Создан':       'sozdan',
}

DB_FIELDS = list(COLUMN_MAP.values())
INSERT_SQL = f"""
    INSERT INTO staging_excel ({', '.join(DB_FIELDS)})
    VALUES ({', '.join(['%s'] * len(DB_FIELDS))})
"""


class Command(BaseCommand):
    help = 'import_excel'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str)

    def handle(self, *args, **options):
        filepath = options['filepath']
        try:
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        except FileNotFoundError:
            raise CommandError(f'file not found: {filepath}')
        except Exception as e:
            raise CommandError(f'error: {e}')

        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise CommandError('file is empty')

        col_idx_to_field = {}
        for idx, cell_val in enumerate(header_row):
            if cell_val is None:
                continue
            header = str(cell_val).strip()
            if header in COLUMN_MAP:
                col_idx_to_field[idx] = COLUMN_MAP[header]

        if not col_idx_to_field:
            raise CommandError('no matching columns found')

        records = []
        for row in rows_iter:
            if all(cell is None for cell in row):
                continue
            record = {f: None for f in DB_FIELDS}
            for idx, field in col_idx_to_field.items():
                cell_val = row[idx] if idx < len(row) else None
                if cell_val is not None:
                    record[field] = str(cell_val).strip()
            records.append(tuple(record[f] for f in DB_FIELDS))

        wb.close()

        with connection.cursor() as cur:
            cur.execute('TRUNCATE TABLE staging_excel RESTART IDENTITY')
            cur.executemany(INSERT_SQL, records)

        self.stdout.write(f'loaded {len(records)} rows')