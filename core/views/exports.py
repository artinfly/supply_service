"""Раздел «Отчёты в Excel»: страница выбора и все выгрузки .xlsx.

Простые выгрузки (история, дубликаты, появившиеся договоры) — это SQL из
services/queries.py, записанный в таблицу через _export_simple. КДР и
договоры по контрагенту собираются здесь же, авансы — на шаблоне со
сводной таблицей (services/reports/pivot.py).
"""

from collections import defaultdict
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from ..services.queries import (
    YEAR_COL,
    advances,
    contract_dupes,
    contract_dupes_by_order,
    contracts_appeared,
    contracts_by_agent_filter,
    dict_rows,
    distinct_agents,
)
from ..services.queries import export_contracts_by_agent as query_contracts_by_agent
from ..services.queries import (
    history_fact,
    history_plan,
    history_status,
    kdr_delta,
    kdr_export,
    valid_date,
)
from ..services.reports.excel import make_wb, xlsx_response
from ..services.reports.pivot import build_advances_xlsx
from .common import base_context

# --- Страница раздела ---


@login_required
def export_page(request):
    """Страница выбора отчётов для экспорта в Excel."""
    with connection.cursor() as cur:
        cur.execute(distinct_agents())
        agents = [r[0] for r in cur.fetchall()]

    ctx = base_context()
    ctx["agents"] = agents
    return render(request, "export.html", ctx)


# --- Вспомогательные функции ---


def _fv(v):
    """Преобразует значение в float, возвращает 0 для None."""
    return float(v or 0)


def _pct(a, b):
    """Вычисляет процент от деления a на b."""
    return round(_fv(a) / _fv(b) * 100, 1) if _fv(b) else 0.0


def _igk4(s):
    """Возвращает последние 4 символа ИГК."""
    return (s or "")[-4:]


def _export_simple(sql, params, name, headers, col_widths):
    """Выполняет SQL-запрос и возвращает Excel-файл."""
    with connection.cursor() as cur:
        cur.execute(sql, params)
        rows = dict_rows(cur)
    return xlsx_response(
        make_wb(name, headers, col_widths, [list(row.values()) for row in rows]),
        name,
    )


def _year_check(year):
    """Проверяет, существует ли колонка года. Возвращает имя колонки или None."""
    return YEAR_COL.get(str(year))


# --- Экспорт истории изменений ---


@login_required
def export_history_status(request):
    """Экспорт истории изменений статусов договоров."""
    return _export_simple(
        history_status(),
        [],
        "история_статусов",
        [
            "ИГК",
            "Контрагент",
            "ЦФО",
            "Договор",
            "Статус (было)",
            "Статус (стало)",
            "Тип платежа",
            "Предмет",
            "План, руб.",
            "Факт, руб.",
            "Дата изменения",
            "Дата загрузки",
            "Год ИГК",
        ],
        [10, 40, 8, 50, 25, 25, 15, 50, 16, 16, 12, 12, 12],
    )


@login_required
def export_history_plan(request):
    """Экспорт истории изменений плановых сумм."""
    return _export_simple(
        history_plan(),
        [],
        "история_плана",
        [
            "ИГК",
            "Контрагент",
            "ЦФО",
            "Договор",
            "Тип платежа",
            "Предмет",
            "План (было), руб.",
            "План (стало), руб.",
            "% от суммы (было)",
            "% от суммы (стало)",
            "Дата изменения",
            "Год ИГК",
        ],
        [10, 40, 8, 50, 15, 50, 16, 16, 14, 14, 12, 12],
    )


@login_required
def export_history_fact(request):
    """Экспорт истории изменений фактических сумм."""
    return _export_simple(
        history_fact(),
        [],
        "история_факта",
        [
            "ИГК",
            "Контрагент",
            "ЦФО",
            "Договор",
            "Тип платежа",
            "Предмет",
            "Факт (было), руб.",
            "Факт (стало), руб.",
            "Дата изменения",
            "Год ИГК",
        ],
        [10, 40, 8, 50, 15, 50, 16, 16, 12, 12],
    )


# --- Экспорт появившихся договоров ---


APPEARED_HEADERS = [
    "Дата загрузки",
    "Причина",
    "ИГК",
    "ЦФО",
    "Контрагент",
    "Договор",
    "Предмет",
    "Заказ",
    "Этап",
    "Дата плана",
    "Состояние",
    "План, руб.",
    "Сумма договора, руб.",
]
APPEARED_WIDTHS = [14, 12, 10, 8, 40, 50, 50, 20, 15, 12, 18, 16, 20]


@login_required
def export_appeared_concluded(request):
    """Экспорт появившихся заключённых договоров."""
    sql, params = contracts_appeared("concluded")
    return _export_simple(
        sql, params, "новые_заключённые", APPEARED_HEADERS, APPEARED_WIDTHS
    )


@login_required
def export_appeared_not_concluded(request):
    """Экспорт появившихся незаключённых договоров."""
    sql, params = contracts_appeared("not_concluded")
    return _export_simple(
        sql, params, "новые_незаключённые", APPEARED_HEADERS, APPEARED_WIDTHS
    )


# --- Экспорт дубликатов ---


def _dupes_args(request):
    """Извлекает параметры ЦФО и года из запроса."""
    return request.GET.get("cfo", "").strip(), request.GET.get("year", "").strip()


@login_required
def export_contract_dupes(request):
    """Экспорт дубликатов договоров."""
    sql, params = contract_dupes(*_dupes_args(request))
    return _export_simple(
        sql,
        params,
        "дубли_договоров",
        [
            "ИГК",
            "ЦФО",
            "Контрагент",
            "Договор",
            "Предмет",
            "Заказ",
            "Этап",
            "Дата плана",
            "Хеш",
        ],
        [10, 8, 40, 50, 50, 20, 15, 12, 12],
    )


@login_required
def export_contract_dupes_by_order(request):
    """Экспорт дубликатов договоров по заказу."""
    sql, params = contract_dupes_by_order(*_dupes_args(request))
    return _export_simple(
        sql,
        params,
        "дубли_по_заказу",
        [
            "ИГК",
            "ЦФО",
            "Предмет",
            "Заказ",
            "Строк",
            "Договоров",
            "Контрагентов",
            "Сумма плана, руб.",
        ],
        [10, 8, 50, 20, 10, 12, 14, 20],
    )


# --- Экспорт КДР ---


# Суммируемые поля строки КДР (для строк «Итого» по ИГК и общего «ИТОГО»)
KDR_SUM_KEYS = [
    "total_count",
    "total_sum",
    "concl_count",
    "concl_sum",
    "year_count",
    "year_sum",
    "year_concl_count",
    "year_concl_sum",
    "year_not_concl_count",
    "year_not_concl_sum",
    "pp_plan",
    "pp_fact",
]
# Номер колонки (с 1) -> формат числа
KDR_FORMATS = {
    4: "#,##0.00",
    6: "#,##0.00",
    8: "#,##0.00",
    11: "#,##0.00",
    15: "#,##0.00",
    16: "#,##0.00",
    17: "#,##0.00",
    10: '0.0"%"',
    12: '0.0"%"',
    18: '0.0"%"',
}
KDR_WIDTHS = [10, 6, 12, 14, 12, 16, 12, 14, 12, 12, 16, 14, 12, 16, 14, 14, 12, 16, 17]


def _kdr_headers(year, period_text):
    """Заголовки колонок КДР; period_text — « с ДД.ММ.ГГГГ по ДД.ММ.ГГГГ» или пусто."""
    return [
        "ИГК",
        "ЦФО",
        "Всего договоров, шт.",
        "Сумма всех договоров, млн.руб.",
        "Заключено, шт.",
        "Сумма заключённых договоров (всех), млн.руб.",
        f"Всего договоров на {year}г., шт.",
        f"Сумма договоров на {year}г., млн.руб.",
        f"Заключено договоров на {year}г., шт.",
        f"% контрактации {year}г. (по количеству)",
        f"Сумма заключённых договоров на {year}г., млн.руб.",
        f"% контрактации {year}г. (по сумме)",
        f"Заключено{period_text}, шт.",
        f"Не заключено на {year}г., шт.",
        f"Сумма незаключённых договоров на {year}г., млн.руб.",
        f"Плановая сумма аванса в {year}г., млн.руб.",
        f"Фактическая сумма аванса на {year}г., млн.руб.",
        f"% авансирования на {year}г.",
        "Примечание",
    ]


def _kdr_row(r, igk_label, cfo_label, delta):
    """Строка таблицы КДР из агрегатов r; delta — заключено за период."""
    return [
        igk_label,
        cfo_label,
        _fv(r["total_count"]),
        _fv(r["total_sum"]),
        _fv(r["concl_count"]),
        _fv(r["concl_sum"]),
        _fv(r["year_count"]),
        _fv(r["year_sum"]),
        _fv(r["year_concl_count"]),
        _pct(r["year_concl_count"], r["year_count"]),
        _fv(r["year_concl_sum"]),
        _pct(r["year_concl_sum"], r["year_sum"]),
        delta,
        _fv(r["year_not_concl_count"]),
        _fv(r["year_not_concl_sum"]),
        _fv(r["pp_plan"]),
        _fv(r["pp_fact"]),
        _pct(r["pp_fact"], r["pp_plan"]),
    ]


def _kdr_sum(rows):
    """Сумма агрегатов по группе строк."""
    return {k: sum(_fv(r[k]) for r in rows) for k in KDR_SUM_KEYS}


def _kdr_table(detail_rows, delta_map):
    """Строки КДР и их виды: по каждому ИГК «Итого», затем ЦФО; в конце «ИТОГО».

    delta_map: {(последние 4 символа ИГК, ЦФО): заключено за период}; пустой,
    если период не задан. В «Итого» входят только положительные дельты.
    """
    igk_groups = defaultdict(list)
    for r in detail_rows:
        igk_groups[r["igk"]].append(r)

    rows, kinds = [], []
    total_delta = 0
    for igk, grp in igk_groups.items():
        deltas = [delta_map.get((_igk4(r["igk"]), r["cfo"]), 0) for r in grp]
        group_delta = sum(d for d in deltas if d > 0)
        total_delta += group_delta

        rows.append(_kdr_row(_kdr_sum(grp), igk, "Итого", group_delta))
        kinds.append("subtotal")
        for r, delta in zip(grp, deltas, strict=True):
            rows.append(_kdr_row(r, "", r["cfo"], delta))
            kinds.append("normal")

    rows.append(_kdr_row(_kdr_sum(detail_rows), "ИТОГО", "", total_delta))
    kinds.append("total")
    return rows, kinds


def _ru_date(iso):
    """«2025-03-15» -> «15.03.2025»."""
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")


@login_required
def export_kdr(request, year):
    """Экспорт отчёта КДР (контрактация договоров) с опциональным периодом."""
    yc = _year_check(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)

    start_date = request.GET.get("start", "").strip()
    end_date = request.GET.get("end", "").strip()
    has_period = bool(start_date and end_date)
    if has_period and not (valid_date(start_date) and valid_date(end_date)):
        return JsonResponse({"error": "недопустимая дата периода"}, status=400)

    delta_map = {}
    with connection.cursor() as cur:
        cur.execute(kdr_export(year))
        detail_rows = dict_rows(cur)
        if has_period:
            cur.execute(*kdr_delta(yc, start_date, end_date))
            delta_map = {(igk, cfo): count for igk, cfo, count in cur.fetchall()}

    rows, kinds = _kdr_table(detail_rows, delta_map)
    period_text = (
        f" с {_ru_date(start_date)} по {_ru_date(end_date)}" if has_period else ""
    )
    return xlsx_response(
        make_wb(
            f"КДР {year}",
            _kdr_headers(year, period_text),
            KDR_WIDTHS,
            rows,
            kinds,
            KDR_FORMATS,
        ),
        f"кдр_{year}",
    )


# --- Экспорт авансов ---


@login_required
def export_advances(request, year):
    """Экспорт отчёта по авансам за год."""
    if not _year_check(year):
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        cur.execute(advances(year))
        rows = dict_rows(cur)
    return build_advances_xlsx(rows, str(year))


# --- Экспорт договоров по контрагентам ---


@login_required
def export_contracts_by_agent(request, year):
    """Экспорт договоров по контрагенту за год."""
    yc = _year_check(year)
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)

    agent = request.GET.get("agent", "").strip()
    conditions, params = contracts_by_agent_filter(yc, agent)
    sql = query_contracts_by_agent(conditions)

    with connection.cursor() as cur:
        cur.execute(sql, params)
        rows = dict_rows(cur)

    headers = [
        "ИГК",
        "Контрагент",
        "ЦФО",
        "Договор",
        "Состояние",
        "Тип платежа",
        "Предмет",
        "Заказ",
        "Этап",
        f"План {year}, руб.",
        f"Факт {year}, руб.",
        "Остаток, руб.",
    ]
    col_w = [15, 40, 8, 50, 20, 15, 50, 20, 15, 18, 18, 18]
    txt_fld = [
        "igk",
        "c_agent",
        "cfo",
        "contract",
        "status",
        "payment_type",
        "item",
        "order",
        "stage",
    ]

    data_rows = [
        [row[f] for f in txt_fld]
        + [_fv(row["plan"]), _fv(row["fact"]), _fv(row["remain"])]
        for row in rows
    ]
    agent_safe = agent[:30].replace(" ", "_") if agent else ""
    filename = f"контрагент_{agent_safe}_{year}" if agent_safe else f"контрагент_{year}"
    return xlsx_response(
        make_wb(f"Договоры {year}", headers, col_w, data_rows),
        filename,
    )
