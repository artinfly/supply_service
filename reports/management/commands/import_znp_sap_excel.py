from reports.services.excel_import import ExcelImportCommand


class Command(ExcelImportCommand):
    table = "staging_znp_sap_excel"
    header_row = 1
    skip_if_blank = 4
    empty_as_null = True
    column_map = {
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
