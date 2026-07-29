from reports.services.excel_import import ExcelImportCommand


class Command(ExcelImportCommand):
    table = "staging_znp_excel"
    header_row = 6
    hash_fields = ("igk", "c_agent", "contract", "stage")
    column_map = {
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
    }
