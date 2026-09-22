"""
Утилиты для генерации Excel-файлов и HTTP-ответов.

Предоставляет функции для создания xlsx-файлов с форматированием
и формирования HTTP-ответов для скачивания.
"""

from io import BytesIO
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# --- Стили ячеек ---

_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_HEADER_FONT = Font(name="Arial", size=9, bold=True, color="000000")
_HEADER_FILL = PatternFill("solid", fgColor="FFFFFF")
_HEADER_ALIGN = Alignment(horizontal="center", wrap_text=True)

_NORMAL_FONT = Font(name="Arial", size=9)
_BOLD_FONT = Font(name="Arial", size=9, bold=True, color="000000")
_TOTAL_FILL = PatternFill("solid", fgColor="C0C0C0")

# --- Транслитерация для ASCII-имён файлов ---

_TRANSLIT = str.maketrans(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ ",
    "abvgdeejzijklmnoprstufxccssiieeuaABVGDEEJZIJKLMNOPRSTUFXCCSSIIEEUA_",
)


def _get_number_format(val):
    """Возвращает формат числа для Excel: '0' для целых, '0.00' для дробных."""
    if isinstance(val, int) or (isinstance(val, float) and val.is_integer()):
        return "0"
    return "0.00"


def make_wb(sheet_name, headers, col_widths, rows_data, kinds=None, formats=None):
    """
    Создаёт xlsx-файл с заголовками и данными.

    Args:
        sheet_name: имя листа
        headers: список заголовков колонок
        col_widths: список ширин колонок
        rows_data: список строк данных (каждая строка — список значений)
        kinds: список типов строк ('normal', 'subtotal', 'total')
        formats: словарь {индекс_колонки: формат_числа} для переопределения

    Returns:
        bytes готового .xlsx файла
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.freeze_panes = "A2"

    # Заголовки
    for ci, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = _HEADER_ALIGN
        ws.column_dimensions[get_column_letter(ci)].width = w

    # Данные
    for ri, row in enumerate(rows_data, 2):
        kind = kinds[ri - 2] if kinds else "normal"
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.border = _BORDER
            is_num = isinstance(val, (int, float)) and not isinstance(val, bool)

            # Применение стиля по типу строки
            if kind == "total":
                cell.font = _BOLD_FONT
                cell.fill = _TOTAL_FILL
                cell.alignment = Alignment(horizontal="right" if is_num else "left")
            elif kind == "subtotal":
                cell.font = _BOLD_FONT
                cell.fill = _TOTAL_FILL
                cell.alignment = Alignment(horizontal="right" if is_num else "left")
            else:
                cell.font = _NORMAL_FONT
                if is_num:
                    cell.alignment = Alignment(horizontal="right")

            # Формат числа
            if is_num:
                if formats and ci in formats:
                    cell.number_format = formats[ci]
                else:
                    cell.number_format = _get_number_format(val)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_response(data, filename_ru):
    """
    Формирует HTTP-ответ для скачивания xlsx-файла.

    Автоматически добавляет текущую дату к имени файла и создаёт
    как ASCII-версию (для совместимости), так и UTF-8 версию имени.

    Args:
        data: bytes содержимого файла
        filename_ru: имя файла на русском (без расширения и даты)

    Returns:
        HttpResponse с заголовками для скачивания
    """
    today = timezone.localdate().strftime("%d_%m_%Y")
    fname_ascii = f"{filename_ru.translate(_TRANSLIT)}_{today}.xlsx"
    fname_utf8 = quote(f"{filename_ru}_{today}.xlsx")
    response = HttpResponse(
        data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{fname_utf8}"
    )
    return response
