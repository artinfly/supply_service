# Колонки файла договоров. Все перечисленные обязательны:
# нет хотя бы одной — загрузка отменяется.
from django.core.management.base import BaseCommand

from reports.services.excel_import import (
    map_columns,
    open_sheet,
    read_values,
    replace_table,
)

TABLE = "staging_excel"
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
    "ДатаПланПодп": "dataplan",
    "СУММА договора": "summa_dogovora",
    "ГодИГК": "god_igk",
}
FIELDS = list(COLUMN_MAP.values())
HASH_COLUMNS = ("igk", "kontragent", "dogovor", "etap_grafika")


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        wb, rows = open_sheet(options["filepath"])
        try:
            positions = map_columns(rows, COLUMN_MAP, self, required=HASH_COLUMNS)
            data = [
                tuple(read_values(row, positions, FIELDS)[f] for f in FIELDS)
                for row in rows
                if any(row)
            ]
        finally:
            wb.close()

        replace_table(TABLE, FIELDS, data)
        self.stdout.write(f"загружено строк: {len(data)}")
