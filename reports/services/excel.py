from io import BytesIO
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_HEADER_FONT = Font(name="Arial", size=9, bold=True, color="000000")
_HEADER_FILL = PatternFill("solid", fgColor="FFFFFF")

_NORMAL_FONT = Font(name="Arial", size=9)
_BOLD_FONT = Font(name="Arial", size=9, bold=True, color="000000")
_TOTAL_FILL = PatternFill("solid", fgColor="C0C0C0")

_ALIGN_HEADER = Alignment(horizontal="center", wrap_text=True)
_ALIGN_LEFT = Alignment(horizontal="left")
_ALIGN_RIGHT = Alignment(horizontal="right")

_TRANSLIT = str.maketrans(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ ",
    "abvgdeejzijklmnoprstufxccssiieeuaABVGDEEJZIJKLMNOPRSTUFXCCSSIIEEUA_",
)


def _get_number_format(value):
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return "0"
    return "0.00"


def make_wb(sheet_name, headers, col_widths, rows_data, kinds=None, formats=None):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.freeze_panes = "A2"

    for ci, (header, width) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=ci, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = _ALIGN_HEADER
        ws.column_dimensions[get_column_letter(ci)].width = width

    for ri, row in enumerate(rows_data, 2):
        kind = kinds[ri - 2] if kinds else "normal"

        for ci, value in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=value)
            cell.border = _BORDER

            is_num = isinstance(value, (int, float)) and not isinstance(value, bool)

            if kind in ("total", "subtotal"):
                cell.font = _BOLD_FONT
                cell.fill = _TOTAL_FILL
                cell.alignment = _ALIGN_RIGHT if is_num else _ALIGN_LEFT
            else:
                cell.font = _NORMAL_FONT
                if is_num:
                    cell.alignment = _ALIGN_RIGHT

            if is_num:
                if formats and ci in formats:
                    cell.number_format = formats[ci]
                else:
                    cell.number_format = _get_number_format(value)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_response(data, filename_ru):
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
