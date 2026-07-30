from django.core.management.base import BaseCommand

from reports.services.excel_import import (
    map_columns,
    open_sheet,
    read_values,
    replace_table,
)
from reports.services.znp_linking import contract_hash

TABLE = "staging_znp_excel"
HEADER_ROW = 1
COLUMN_MAP = {
    "ИГК договора": "igk",
    "ИГК заявки": "znp_igk",
    "Контрагент": "c_agent",
    "ДокументПланирования.Номер": "plan_doc",
    "Этап": "stage",
    "Назначение платежа": "payment_purpose",
    "Договор": "contract",
    "Прогнозная дата оплаты": "plan_payment_date",
    "Фактическая дата оплаты": "fact_payment_date",
    "Сумма руб планирования": "plan_sum",
    "Сумма руб оплаты": "fact_sum",
    "ТипПлатежа": "znp_payment_type",
    "Статус": "znp_status",
}
FIELDS = list(COLUMN_MAP.values()) + ["crc32_hash"]


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        wb, rows = open_sheet(options["filepath"], HEADER_ROW)
        try:
            positions = map_columns(rows, COLUMN_MAP, self)
            data = []
            for row in rows:
                if not any(row):
                    continue
                record = read_values(row, positions, FIELDS)
                record["crc32_hash"] = contract_hash(
                    record["igk"],
                    record["c_agent"],
                    record["contract"],
                    record["stage"],
                )
                data.append(tuple(record[f] for f in FIELDS))
        finally:
            wb.close()

        replace_table(TABLE, FIELDS, data)
        self.stdout.write(f"загружено строк: {len(data)}")
