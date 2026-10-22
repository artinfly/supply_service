"""Страница «Загрузка данных»: договоры, заявки ФЗД, заявки SAP.

Файл сохраняется во временный файл и передаётся management-команде
(load_contracts / load_znp / load_znp_sap) — та же команда работает
и из консоли: python manage.py load_contracts путь_к_файлу.xlsx
"""

import logging
import os
import tempfile
from io import StringIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.shortcuts import render
from openpyxl.utils import get_column_letter

from ..services.importing.excel_import import (
    CONTRACT_COLUMNS,
    ZNP_COLUMNS,
    ZNP_SAP_COLUMNS,
)
from .common import base_context

logger = logging.getLogger(__name__)

# Тип файла из выпадающего списка -> management-команда загрузки
FILE_TYPE_COMMANDS = {
    "contracts": "load_contracts",
    "znp": "load_znp",
    "znp_sap": "load_znp_sap",
}

# Подписи колонок файла SAP: там колонки берутся по номеру, а не по заголовку
_SAP_LABELS = {
    "igk": "ИГК",
    "cfo": "ЦФО",
    "c_agent": "Контрагент",
    "reg_num": "Рег. номер",
    "items": "Предметы",
    "vv_sum": "Сумма",
    "bank_name": "Банк",
    "stage_e": "Дата передачи в 18 отдел",
    "stage_f": "Дата подтверждения 18 отделом",
    "stage_c": "Дата согласования для реестра",
    "payment_possible": "Возможная дата платежа",
    "c_type": "Тип (ГОЗ)",
    "normalize_doc_num": "Номер документа оплаты",
    "created_date": "Дата создания заявки",
}


def _sap_column_hints():
    """«Буква столбца — что в нём» для файла SAP, по порядку столбцов."""
    return [
        f"{get_column_letter(idx + 1)} — {_SAP_LABELS.get(field, field)}"
        for field, idx in sorted(ZNP_SAP_COLUMNS.items(), key=lambda kv: kv[1])
    ]


# Подсказка на странице: какие колонки нужны в файле каждого типа
FILE_TYPE_COLUMNS = {
    "contracts": list(CONTRACT_COLUMNS),
    "znp": list(ZNP_COLUMNS),
    "znp_sap": _sap_column_hints(),
}

FILE_TYPE_LABELS = {
    "contracts": "Договоры",
    "znp": "ЗнП (ФЗД)",
    "znp_sap": "ЗнП (SAP)",
}


@login_required
def upload_excel(request):
    """Загрузка Excel-файла выбранного типа с последующей нормализацией."""
    result = None
    file_type = request.POST.get("file_type", "contracts")

    if request.method == "POST" and request.FILES.get("excel_file"):
        command = FILE_TYPE_COMMANDS.get(file_type)

        if command is None:
            messages.error(request, f"Неизвестный тип файла: {file_type}")
        else:
            uploaded_file = request.FILES["excel_file"]
            ext = os.path.splitext(uploaded_file.name)[1].lower()

            if ext not in (".xlsx", ".xls"):
                messages.error(
                    request,
                    f"Неподдерживаемый формат файла: {ext or 'без расширения'}. "
                    "Нужен .xlsx или .xls",
                )
            else:
                # Команды загрузки принимают путь к файлу, поэтому кладём его на диск
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    for chunk in uploaded_file.chunks():
                        tmp.write(chunk)
                    tmp_path = tmp.name

                try:
                    out = StringIO()
                    call_command(command, tmp_path, stdout=out)
                    result = out.getvalue()
                    messages.success(request, "Файл успешно загружен и нормализован")
                except Exception as e:  # показываем пользователю, трассировку — в лог
                    logger.exception(
                        "Ошибка загрузки файла %s (%s)", uploaded_file.name, file_type
                    )
                    text = str(e)
                    messages.error(
                        request,
                        text if text.startswith("Ошибка") else f"Ошибка: {text}",
                    )
                    result = text
                finally:
                    os.unlink(tmp_path)

    ctx = base_context()
    ctx.update(
        {
            "result": result,
            "file_types": FILE_TYPE_LABELS,
            "file_columns": FILE_TYPE_COLUMNS,
            "selected_type": file_type,
        }
    )
    return render(request, "upload.html", ctx)
