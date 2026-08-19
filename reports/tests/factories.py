import os
import tempfile
from io import StringIO

from django.core.management import call_command
from openpyxl import Workbook

from reports.services.excel_import import (
    CONTRACT_COLUMNS,
    ZNP_COLUMNS,
    ZNP_SAP_COLUMNS,
)


def _write(columns, rows):
    headers = list(columns)
    fields = [columns[h] for h in headers]
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append([row.get(f) for f in fields])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    wb.save(tmp.name)
    return tmp.name


def contracts_file(rows):
    return _write(CONTRACT_COLUMNS, rows)


def znp_file(rows):
    return _write(ZNP_COLUMNS, rows)


def znp_sap_file(rows):
    return _write(ZNP_SAP_COLUMNS, rows)


def contract_row(**over):
    row = {
        "igk": "2426187301032442228107",
        "kontragent": "ООО Ромашка",
        "cfo": "421",
        "dogovor": "Д-1",
        "sostoyanie": "Исполняется",
        "tip_platezha": "Аванс",
        "predmet": "Насосы",
        "zakaz": "З-1",
        "plan": 100.0,
        "fakt": 50.0,
        "ostatok": 50.0,
        "tol": 0,
        "etap_grafika": "Этап 1",
        "dataplan": "01.03.2026",
        "summa_dogovora": 1000.0,
        "god_igk": "2026",
    }
    row.update(over)
    return row


def znp_row(**over):
    row = {
        "igk": "2426187301032442228107",
        "znp_igk": "2426187301032442228107",
        "c_agent": "ООО Ромашка",
        "plan_doc": "ЗнП-1",
        "stage": "Этап 1",
        "payment_purpose": "Аванс по договору",
        "contract": "Д-1",
        "plan_payment_date": "1 марта 2026",
        "fact_payment_date": "5 марта 2026",
        "plan_sum": 0,
        "fact_sum": 0,
        "znp_payment_type": "Аванс",
        "znp_status": "Утвержден",
        "znp_date": "01.02.2026",
    }
    row.update(over)
    return row


def znp_sap_row(**over):
    row = {
        "igk": "2426187301032442228107",
        "cfo": "421",
        "c_agent": "ООО Ромашка",
        "reg_num": "SAP-1",
        "items": "Насосы",
        "vv_sum": 100.0,
        "bank_name": "Банк",
        "c_type": "ГОЗ",
        "stage_e": "2026-03-01",
        "stage_f": "2026-03-02",
        "payment_possible": "2026-03-03",
        "normalize_doc_num": "ДВ-1",
    }
    row.update(over)
    return row


def load(command, path):
    try:
        call_command(command, path, stdout=StringIO())
    finally:
        os.unlink(path)
