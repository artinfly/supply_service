from django.core.management.base import BaseCommand, CommandError
from django.db import connection
import openpyxl


COLUMN_MAP = {
    'ИГК':           'igk',
    'Контрагент':     'kontragent',
    'ЦФО':           'cfo',
    'Договор':        'dogovor',
    'Состояние':      'sostoyanie',
    'Тип платежа':    'tip_platezha',
    'Предмет':        'predmet',
    'Заказ':          'zakaz',
    'ПЛАН':           'plan',
    'ФАКТ':           'fakt',
    'Тол':            'tol',
    'Этап графика':   'etap_grafika',
    'ДатаПЛАН':       'dataplan',
    'Создан':         'sozdan',
    'ГодИГК':         'god_igk',
}

DB_FIELDS    = list(COLUMN_MAP.values())
INSERT_SQL   = (
    f"INSERT INTO staging_excel ({', '.join(DB_FIELDS)}) "
    f"VALUES ({', '.join(['%s'] * len(DB_FIELDS))})"
)


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str)

    def handle(self, *args, **options):
        filepath = options['filepath']

        try:
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        except FileNotFoundError:
            raise CommandError(f'file not found: {filepath}')
        except Exception as exc:
            raise CommandError(str(exc))

        ws   = wb.active
        rows = ws.iter_rows(values_only=True)

        try:
            header = next(rows)
        except StopIteration:
            raise CommandError('file is empty')

        col_map = {
            i: COLUMN_MAP[str(cell).strip()]
            for i, cell in enumerate(header)
            if cell and str(cell).strip() in COLUMN_MAP
        }

        if not col_map:
            raise CommandError('no matching columns found in header')

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

        with connection.cursor() as cur:
            cur.execute('TRUNCATE staging_excel RESTART IDENTITY')
            if data:
                cur.executemany(INSERT_SQL, data)

        self.stdout.write(f'loaded {len(data)} rows into staging_excel')