# Колонки файла заявок ЗнП (SAP). Берутся только строки с типом ГОЗ.
from django.core.management.base import BaseCommand

from reports.services.excel_import import (
    map_columns,
    open_sheet,
    read_values,
    replace_table,
)

TABLE = "staging_znp_sap_excel"
COLUMN_MAP = {
    "ИГК (по договору)": "igk",
    "Отдел-исполнитель": "cfo",
    "Наименование кредитора": "c_agent",
    "Регистрационный номер": "reg_num",
    "Текст": "items",
    "Сумма во ВВ": "vv_sum",
    "Наименование Банка": "bank_name",
    "ЗнП 421 отдел (ГОЗ) - (E)": "stage_e",
    "ЗнП 18 отдел (ГОЗ) - (F)": "stage_f",
    "Платеж возможен - ( )": "payment_possible",
    "СП/ГП": "c_type",
    "ДокумВыравнивания": "normalize_doc_num",
}
FIELDS = list(COLUMN_MAP.values())
ITEMS_COLUMN = 4


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        wb, rows = open_sheet(options["filepath"])
        try:
            positions = map_columns(rows, COLUMN_MAP, self)
            data = []
            for row in rows:
                if not any(row):
                    continue
                if len(row) > ITEMS_COLUMN and row[ITEMS_COLUMN] == "":
                    continue
                record = read_values(row, positions, FIELDS, empty_as_null=True)
                data.append(tuple(record[f] for f in FIELDS))
        finally:
            wb.close()

        replace_table(TABLE, FIELDS, data)
        self.stdout.write(f"загружено строк: {len(data)}")
