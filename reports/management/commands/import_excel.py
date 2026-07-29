from reports.services.excel_import import ExcelImportCommand


class Command(ExcelImportCommand):
    table = "staging_excel"
    header_row = 1
    required_columns = ("igk", "kontragent", "dogovor", "etap_grafika")
    column_map = {
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
        "ДатаПЛАН": "dataplan",
        "Создан": "sozdan",
        "ГодИГК": "god_igk",
    }
