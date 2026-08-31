"""
Фабрики тестовых данных для загрузки.

Создают временные Excel-файлы с тестовыми данными и загружают их
через management-команды (те же, что используются в production).

Использование в тестах:
    load("load_contracts", contracts_file([contract_row()]))
    load("load_znp", znp_file([znp_row()]))

Каждая фабрика строк возвращает словарь со значениями по умолчанию.
Переопределить любое поле можно через kwargs:
    contract_row(plan=200.0)  # меняет план на 200
"""

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

# ============================================================================
# Создание Excel-файлов
# ============================================================================


def _write(columns, rows):
    """
    Создаёт временный Excel-файл с заголовками и строками.

    Параметры:
    - columns: словарь {заголовок: поле таблицы}, из которого берутся
      заголовки и порядок колонок
    - rows: список словарей со значениями по полям

    Возвращает путь к временному файлу. Вызывающий код должен удалить
    файл после использования (это делает `load()`).
    """
    headers = list(columns)
    fields = [columns[h] for h in headers]
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append([row.get(f) for f in fields])
    # delete=False: файл нужен после закрытия контекстного менеджера
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    wb.save(tmp.name)
    return tmp.name


def contracts_file(rows):
    """Создаёт файл выгрузки договоров с указанными строками."""
    return _write(CONTRACT_COLUMNS, rows)


def znp_file(rows):
    """Создаёт файл выгрузки заявок ФЗД с указанными строками."""
    return _write(ZNP_COLUMNS, rows)


def znp_sap_file(rows):
    """Создаёт файл выгрузки заявок SAP с указанными строками."""
    return _write(ZNP_SAP_COLUMNS, rows)


# ============================================================================
# Строки данных
# ============================================================================


def contract_row(**over):
    """
    Строка договора со значениями по умолчанию.

    Переопределить любое поле можно через kwargs:
        contract_row(plan=200.0, sostoyanie="Исполнен")

    Значения по умолчанию соответствуют минимальной валидной строке:
    все поля заполнены, суммы ненулевые (кроме допуска).
    """
    row = {
        "igk": "2426187301032442228107",  # Длинный ИГК как в реальных файлах
        "kontragent": "ООО Ромашка",
        "cfo": "421",
        "dogovor": "Д-1",
        "sostoyanie": "Исполняется",  # Заключённый статус
        "tip_platezha": "Аванс",
        "predmet": "Насосы",
        "zakaz": "З-1",
        "plan": 100.0,
        "fakt": 50.0,
        "ostatok": 50.0,
        "tol": 0,  # Допуск 0: заявка нужна всегда
        "etap_grafika": "Этап 1",
        "dataplan": "01.03.2026",
        "summa_dogovora": 1000.0,
        "god_igk": "2026",  # Год для флагов y25/y26/y27
    }
    row.update(over)
    return row


def znp_row(**over):
    """
    Строка заявки ФЗД со значениями по умолчанию.

    Значения подобраны так, чтобы заявка привязывалась к позиции
    договора из `contract_row()` (совпадают ИГК, контрагент, договор, этап).
    """
    row = {
        "igk": "2426187301032442228107",  # Совпадает с contract_row
        "znp_igk": "2426187301032442228107",
        "c_agent": "ООО Ромашка",  # Совпадает с contract_row
        "plan_doc": "ЗнП-1",
        "stage": "Этап 1",  # Совпадает с contract_row
        "payment_purpose": "Аванс по договору",
        "contract": "Д-1",  # Совпадает с contract_row
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
    """
    Строка заявки SAP со значениями по умолчанию.

    Тип «ГОЗ» — заявка проходит фильтр загрузки
    (загружаются только ГОЗ, «СП» отфильтровываются).
    """
    row = {
        "igk": "2426187301032442228107",
        "cfo": "421",
        "c_agent": "ООО Ромашка",
        "reg_num": "SAP-1",
        "items": "Насосы",
        "vv_sum": 100.0,
        "bank_name": "Банк",
        "c_type": "ГОЗ",  # Только ГОЗ проходят фильтр
        "stage_e": "2026-03-01",
        "stage_f": "2026-03-02",
        "payment_possible": "2026-03-03",
        "normalize_doc_num": "ДВ-1",
    }
    row.update(over)
    return row


# ============================================================================
# Загрузка файлов
# ============================================================================


def load(command, path):
    """
    Загружает файл через management-команду и удаляет временный файл.

    Использует те же команды, что и в production:
    load_contracts, load_znp, load_znp_sap.

    Временный файл удаляется в finally — даже если команда упала.
    """
    try:
        call_command(command, path, stdout=StringIO())
    finally:
        os.unlink(path)
