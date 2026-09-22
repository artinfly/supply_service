"""
Анализ отчётов ЕИС ГОЗ (форма исполнения госконтракта) из ZIP-архива .xls
файлов. Один .xls = один контракт, имя файла = последние 4 цифры ИГК.

Расположение нужных показателей на листе "Лист_1" фиксировано (это форма
госсистемы, не меняется): колонка D — целевые (план), колонка G — сальдо
операций (факт). Ниже — 0-индексированные координаты для xlrd.
"""

import zipfile
from io import BytesIO

import xlrd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SHEET_NAME = "Лист_1"

_PLAN_COL = 3  # столбец D
_FACT_COL = 6  # столбец G

# Строки, которые есть и в целевых, и в фактических показателях.
_LINE_ROWS = {
    "shipment": 31,  # 3.   Отгрузка товара, выполнение работ, оказание услуг
    "cost": 32,  # 3.1  Себестоимость реализованной продукции
    "amr": 33,  # 3.2  Административно-управленческие расходы
    "commercial": 34,  # 3.3  Коммерческие расходы
    "credit_pct": 35,  # 3.4  Проценты по кредитам банка
    "profit": 37,  # 3.6  Прибыль контракта
}

# Строки, которые есть только в столбце "факт" (сальдо операций).
_FACT_ONLY_ROWS = {
    "financing": 4,  # 1.     Финансирование контракта
    "distribution": 9,  # 2.     Распределение ресурсов контракта
    "materials": 15,  # 2.2.1  Материалы на складах (ТМЦ)
    "vat_in": 16,  # 2.2.2  НДС входящий
    "wip": 21,  # 2.3    Производство (НЗП)
    "resource_delta": 38,  # 4.  (+/-) Привлечение/перенаправление ресурсов
}

HEADERS = [
    "№ п/п", "ГК", "Наименование", "",
    "Отгрузка (п.3)", "Себестоимость (п.3.1)", "АУР (п.3.2)",
    "КР (п.3.3)", "НДС", "% кредит (п.3.4)", "Прибыль в отчёте (п.3.6)",
    "Прибыль (проверка)", "Рент. к с/с, % (проверка)",
    "Рент. к с/с, % по прибыли в отчёте",
    "Финансирование контракта (п.1)", "Распределение ресурсов (п.2)",
    "+/- ресурсов ГК (проверка)", "+/- ресурсов ГК (п.4)",
    "НЗП (п.2.3)", "ТМЦ (п.2.2.1)", "НДС вх. (п.2.2.2)",
    "Примечание", "Комментарий",
]
_COL_WIDTHS = [6, 10, 16, 14] + [14] * 17 + [28, 28]

# Позиции ключевых колонок (1-индексные, как в Excel).
_K_COL, _L_COL, _M_COL, _N_COL = 11, 12, 13, 14
_Q_COL, _R_COL = 17, 18
_PERCENT_COLS = {_M_COL, _N_COL}

_RENT_THRESHOLD = 0.075  # порог рентабельности для подсветки — 7.5%
_MISMATCH_EPS = 1.0  # допуск в рублях при сравнении "проверка" со значением формы

_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_FONT = Font(name="Arial", size=9)
_BOLD_FONT = Font(name="Arial", size=9, bold=True)
_RED_FONT = Font(name="Arial", size=9, color="9C0006")
_RED_FILL = PatternFill("solid", fgColor="FFC7CE")
_WARN_FILL = PatternFill("solid", fgColor="FFEB9C")
_SUBTOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")


def _cell_number(sheet, row, col):
    """Число из ячейки; всё нечисловое (пусто, 'Х'-заглушка) — 0.0."""
    try:
        value = sheet.cell_value(row, col)
    except IndexError:
        return 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def _read_contract_file(igk, content):
    try:
        book = xlrd.open_workbook(file_contents=content)
        sheet = book.sheet_by_name(SHEET_NAME)
    except Exception as e:
        raise ValueError(f"файл {igk}.xls: {e}") from e

    plan = {k: _cell_number(sheet, r, _PLAN_COL) for k, r in _LINE_ROWS.items()}
    fact = {k: _cell_number(sheet, r, _FACT_COL) for k, r in _LINE_ROWS.items()}
    fact.update(
        {k: _cell_number(sheet, r, _FACT_COL) for k, r in _FACT_ONLY_ROWS.items()}
    )
    return igk, plan, fact


def read_archive(archive_file):
    """
    Читает ZIP-архив с .xls отчётами по контрактам.
    Возвращает список (igk, plan, fact), отсортированный по номеру ИГК.
    Не-.xls файлы в архиве пропускаются.
    """
    contracts = []
    with zipfile.ZipFile(archive_file) as zf:
        for name in zf.namelist():
            if name.endswith("/") or not name.lower().endswith(".xls"):
                continue
            igk = name.rsplit("/", 1)[-1][:-4]
            with zf.open(name) as fh:
                contracts.append(_read_contract_file(igk, fh.read()))

    if not contracts:
        raise ValueError("в архиве не найдено ни одного .xls файла")

    contracts.sort(key=lambda c: (len(c[0]), c[0]))
    return contracts


def _line_metrics(values, vat_rate):
    """Считает 10 показателей (E..N) из шести исходных строк формы."""
    e = values["shipment"]
    f = values["cost"]
    g = values["amr"]
    h = values["commercial"]
    i = e - e / (1 + vat_rate / 100)
    j = values["credit_pct"]
    k = values["profit"]
    l = e - f - g - h - i - j
    m = (l / f) if f else None
    n = (k / f) if f else None
    return [e, f, g, h, i, j, k, l, m, n]


def _deviation(fact_m, plan_m):
    abs_dev = [
        (fv - pv) if isinstance(fv, (int, float)) and isinstance(pv, (int, float)) else None
        for fv, pv in zip(fact_m, plan_m)
    ]
    rel_dev = [
        (av / pv) if av is not None and pv else None for av, pv in zip(abs_dev, plan_m)
    ]
    return abs_dev, rel_dev


def _write_row(ws, row_idx, values, bold=False, force_percent=False):
    """Пишет строку начиная с колонки A, с рамкой и форматом чисел."""
    for ci, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=ci, value=val)
        cell.border = _BORDER
        cell.font = _BOLD_FONT if bold else _FONT
        if bold:
            cell.fill = _SUBTOTAL_FILL
        is_num = isinstance(val, (int, float)) and not isinstance(val, bool)
        if ci in (1, 2):
            cell.alignment = Alignment(horizontal="center")
        elif is_num and ci >= 5:
            is_percent = force_percent or ci in _PERCENT_COLS
            cell.number_format = "0.0%" if is_percent else "#,##0.00"
            cell.alignment = Alignment(horizontal="right")


def _apply_report_checks(ws, row_idx, metrics):
    """
    Подсветка для строк "Целевые" и "Факт":
    - K (прибыль в отчёте) не совпадает с L (прибыль расчётная) — жёлтый;
    - M/N (рентабельность) выше порога — красный.
    Совпадает с реально работавшими правилами условного форматирования
    из исходного файла (остальные диапазоны там были скопированы с ошибкой
    и покрывали не все контракты — здесь применяется ко всем одинаково).
    """
    k, l = metrics[6], metrics[7]
    if isinstance(k, (int, float)) and isinstance(l, (int, float)):
        if abs(k - l) > _MISMATCH_EPS:
            ws.cell(row=row_idx, column=_K_COL).fill = _WARN_FILL
            ws.cell(row=row_idx, column=_L_COL).fill = _WARN_FILL

    for val, col in ((metrics[8], _M_COL), (metrics[9], _N_COL)):
        if isinstance(val, (int, float)) and val > _RENT_THRESHOLD:
            cell = ws.cell(row=row_idx, column=col)
            cell.fill = _RED_FILL
            cell.font = _RED_FONT


def _apply_fact_checks(ws, row_idx, fact_extra):
    """
    Подсветка только для строки "Факт":
    - Q ("+/- ресурсов", расчёт) не совпадает с R (значение из формы) — жёлтый;
    - Q отрицательный — красный (перекрывает жёлтый, если сработали оба).
    """
    q, r = fact_extra[2], fact_extra[3]
    if isinstance(q, (int, float)) and isinstance(r, (int, float)) and abs(q - r) > _MISMATCH_EPS:
        ws.cell(row=row_idx, column=_Q_COL).fill = _WARN_FILL
        ws.cell(row=row_idx, column=_R_COL).fill = _WARN_FILL
    if isinstance(q, (int, float)) and q < 0:
        cell = ws.cell(row=row_idx, column=_Q_COL)
        cell.fill = _RED_FILL
        cell.font = _RED_FONT


def build_report(contracts, vat_rate):
    """
    contracts — результат read_archive(). vat_rate — ставка НДС в процентах
    (например 22 для 22%). Возвращает байты готового .xlsx.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Анализ ГОЗ"
    ws.freeze_panes = "A3"

    ws.cell(row=1, column=1, value="Анализ отчётов ЕИС ГОЗ").font = Font(
        name="Arial", size=11, bold=True
    )

    hdr_font = Font(name="Arial", size=9, bold=True)
    hdr_aln = Alignment(horizontal="center", wrap_text=True)
    for ci, (h, w) in enumerate(zip(HEADERS, _COL_WIDTHS), 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.font = hdr_font
        cell.border = _BORDER
        cell.alignment = hdr_aln
        ws.column_dimensions[get_column_letter(ci)].width = w

    row_i = 3
    for num, (igk, plan, fact) in enumerate(contracts, 1):
        plan_m = _line_metrics(plan, vat_rate)
        fact_m = _line_metrics(fact, vat_rate)
        fact_extra = [
            fact["financing"],
            fact["distribution"],
            fact["distribution"] - fact["financing"],
            fact["resource_delta"],
            fact["wip"],
            fact["materials"],
            fact["vat_in"],
        ]
        abs_dev, rel_dev = _deviation(fact_m, plan_m)

        _write_row(ws, row_i, [num, igk, "", "Целевые", *plan_m])
        _apply_report_checks(ws, row_i, plan_m)
        row_i += 1

        _write_row(ws, row_i, ["", "", "", "Факт", *fact_m, *fact_extra], bold=True)
        _apply_report_checks(ws, row_i, fact_m)
        _apply_fact_checks(ws, row_i, fact_extra)
        row_i += 1

        _write_row(ws, row_i, ["", "", "", "откл.абсол.", *abs_dev])
        row_i += 1

        _write_row(ws, row_i, ["", "", "", "откл.отн.%", *rel_dev], force_percent=True)
        row_i += 1

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
