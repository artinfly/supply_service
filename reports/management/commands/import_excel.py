"""
python manage.py import_excel "path/to/file.xlsx"

Загружает Excel-файл в таблицу staging_excel.
Все значения сохраняются как текст — нормализация отдельной командой.
"""

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Маппинг русских заголовков → поля staging_excel
# Порядок и регистр должны точно совпадать с заголовками в файле
COLUMN_MAP = {
    'ИГК':                   'igk',
    'Контрагент':            'kontragent',
    'Контрагент*':           'kontragent_star',
    'ИНН контрагента':       'inn_kontragenta',
    'ЦФО':                   'cfo',
    'Договор':               'dogovor',
    'Ссылка':                'ssylka',
    'Состояние':             'sostoyanie',
    'Этап графика':          'etap_grafika',
    'Тип платежа':           'tip_platezha',
    'Срок':                  'srok',
    'Подписан':              'podpisan',
    'Код статьи бюджета':    'kod_stati_byudzheta',
    'Тол':                   'tol',
    'Предмет':               'predmet',
    'СчетОрг':               'schetorg',
    'СчетКонтр':             'schetkontr',
    'ПунктЕП':               'punktep',
    'ДатаПодп':              'datapodp',
    'Создан':                'sozdan',
    'ДатаПланПодп':          'dataplanpodp',
    'Объект расчетов':       'obekt_raschetov',
    'Заказ':                 'zakaz',
    'СУММА договора':        'summa_dogovora',
    'Зерк':                  'zerk',
    'ДатаПЛАН':              'dataplan',
    'ПЛАН':                  'plan',
    '%':                     'procent',
    'ФАКТ':                  'fakt',
    '%д':                    'procent_d',
    '%э':                    'procent_e',
    'Остаток':               'ostatok',
    '%э1':                   'procent_e1',
    'ОстатокМакс':           'ostatokmaks',
    'ПланЭтИсп':             'planetisp',
    'Исполнено':             'ispolneno',
    'ПервДата':              'pervdata',
    'ПослДата':              'posldata',
}

DB_FIELDS = list(COLUMN_MAP.values())
PLACEHOLDERS = ', '.join(['%s'] * len(DB_FIELDS))
INSERT_SQL = f"""
    INSERT INTO dbo.staging_excel ({', '.join(DB_FIELDS)})
    VALUES ({PLACEHOLDERS})
"""


class Command(BaseCommand):
    help = 'Загружает Excel в staging_excel (предварительно очищает таблицу)'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Путь к .xlsx файлу')

    def handle(self, *args, **options):
        filepath = options['filepath']

        # ── Открываем файл ─────────────────────────────────────────────
        self.stdout.write(f'Открываем файл: {filepath}')
        try:
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        except FileNotFoundError:
            raise CommandError(f'Файл не найден: {filepath}')
        except Exception as e:
            raise CommandError(f'Ошибка открытия файла: {e}')

        ws = wb.active

        # ── Читаем заголовки ───────────────────────────────────────────
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise CommandError('Файл пуст')

        # Строим маппинг: индекс колонки → имя поля в БД
        col_idx_to_field = {}
        for idx, cell_val in enumerate(header_row):
            if cell_val is None:
                continue
            header = str(cell_val).strip()
            if header in COLUMN_MAP:
                col_idx_to_field[idx] = COLUMN_MAP[header]

        if not col_idx_to_field:
            raise CommandError(
                'Не найдено ни одного совпадающего заголовка. '
                'Проверьте, что первая строка файла содержит заголовки.'
            )

        self.stdout.write(f'Найдено совпадающих колонок: {len(col_idx_to_field)}')

        # ── Читаем строки данных ───────────────────────────────────────
        records = []
        for row in rows_iter:
            # Пропускаем полностью пустые строки
            if all(cell is None for cell in row):
                continue

            # Формируем запись в порядке DB_FIELDS
            record = {f: None for f in DB_FIELDS}
            for idx, field in col_idx_to_field.items():
                cell_val = row[idx] if idx < len(row) else None
                if cell_val is not None:
                    record[field] = str(cell_val).strip()

            records.append(tuple(record[f] for f in DB_FIELDS))

        wb.close()
        self.stdout.write(f'Строк данных для загрузки: {len(records)}')

        # ── Очищаем staging и вставляем ───────────────────────────────
        with connection.cursor() as cur:
            self.stdout.write('Очищаем staging_excel...')
            cur.execute('TRUNCATE TABLE dbo.staging_excel RESTART IDENTITY')

            self.stdout.write('Вставляем данные...')
            # executemany быстрее чем по одной записи
            cur.executemany(INSERT_SQL, records)

        self.stdout.write(self.style.SUCCESS(
            f'✓ Загружено {len(records)} строк в staging_excel.'
        ))