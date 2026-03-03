import pandas as pd
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Загрузка Excel в staging-таблицу dbo.staging_excel'

    def add_arguments(self, parser):
        parser.add_argument('excel_file', type=str, help='Путь к Excel-файлу')

    def handle(self, *args, **options):
        file_path = options['excel_file']
        self.stdout.write(f'Чтение файла {file_path}...')
        df = pd.read_excel(file_path, dtype=str)
        self.stdout.write(f'Найдено строк: {len(df)}')
        df = df.dropna(how='all')
        if len(df) == 0:
            self.stdout.write(self.style.WARNING('Нет данных'))
            return

        column_mapping = {
            'ИГК': 'igk',
            'Контрагент': 'kontragent',
            'Контрагент*': 'kontragent_star',
            'ИНН контрагента': 'inn_kontragenta',
            'ЦФО': 'cfo',
            'Договор': 'dogovor',
            'Ссылка': 'ssylka',
            'Состояние': 'sostoyanie',
            'Этап графика': 'etap_grafika',
            'Тип платежа': 'tip_platezha',
            'Срок': 'srok',
            'Подписан': 'podpisan',
            'Код статьи бюджета': 'kod_stati_byudzheta',
            'Тол': 'tol',
            'Предмет': 'predmet',
            'СчетОрг': 'schetorg',
            'СчетКонтр': 'schetkontr',
            'ПунктЕП': 'punktep',
            'ДатаПодп': 'datapodp',
            'Создан': 'sozdan',
            'ДатаПланПодп': 'dataplanpodp',
            'Объект расчетов': 'obekt_raschetov',
            'Заказ': 'zakaz',
            'СУММА договора': 'summa_dogovora',
            'Зерк': 'zerk',
            'ДатаПЛАН': 'dataplan',
            'ПЛАН': 'plan',
            '%': 'procent',
            'ФАКТ': 'fakt',
            '%д': 'procent_d',
            '%э': 'procent_e',
            'Остаток': 'ostatok',
            '%э1': 'procent_e1',
            'ОстатокМакс': 'ostatokmaks',
            'ПланЭтИсп': 'planetisp',
            'Исполнено': 'ispolneno',
            'ПервДата': 'pervdata',
            'ПослДата': 'posldata'
        }

        missing_rus = set(column_mapping.keys()) - set(df.columns)
        if missing_rus:
            self.stdout.write(self.style.ERROR(f'В Excel отсутствуют колонки: {missing_rus}'))
            return

        table_columns = [
            'igk', 'kontragent', 'kontragent_star', 'inn_kontragenta', 'cfo',
            'dogovor', 'ssylka', 'sostoyanie', 'etap_grafika', 'tip_platezha',
            'srok', 'podpisan', 'kod_stati_byudzheta', 'tol', 'predmet',
            'schetorg', 'schetkontr', 'punktep', 'datapodp', 'sozdan',
            'dataplanpodp', 'obekt_raschetov', 'zakaz', 'summa_dogovora',
            'zerk', 'dataplan', 'plan', 'procent', 'fakt', 'procent_d',
            'procent_e', 'ostatok', 'procent_e1', 'ostatokmaks', 'planetisp',
            'ispolneno', 'pervdata', 'posldata'
        ]

        with connection.cursor() as cursor:
            cursor.execute('TRUNCATE TABLE "dbo"."staging_excel" RESTART IDENTITY;')

        inserted = 0
        with connection.cursor() as cursor:
            for _, row in df.iterrows():
                values = []
                for eng_col in table_columns:
                    rus_col = None
                    for r, e in column_mapping.items():
                        if e == eng_col:
                            rus_col = r
                            break
                    if rus_col is None:
                        values.append(None)
                    else:
                        val = row.get(rus_col)
                        if pd.isna(val):
                            values.append(None)
                        else:
                            values.append(val)
                placeholders = ','.join(['%s'] * len(table_columns))
                sql = f'INSERT INTO "dbo"."staging_excel" ({",".join(table_columns)}) VALUES ({placeholders})'
                try:
                    cursor.execute(sql, values)
                    inserted += 1
                    if inserted % 100 == 0:
                        self.stdout.write(f'Загружено {inserted} строк...')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Ошибка в строке {inserted+2}: {e}'))
        self.stdout.write(self.style.SUCCESS(f'Импорт завершён. Загружено {inserted} строк.'))