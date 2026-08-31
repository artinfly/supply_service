"""
Выгрузки Excel: формирование и отдача .xlsx файлов.

Каждая выгрузка возвращает HttpResponse с content-type
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.

Данные берутся через сырой SQL из services/queries.py,
книга Excel собирается в services/excel.py.
"""

from collections import defaultdict
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse

from ..services.excel import make_wb, xlsx_response
from ..services.pivot import build_advances_xlsx
from ..services.queries import (
    YEAR_COL,
    advances,
    contract_dupes,
    contract_dupes_by_order,
    contracts_appeared,
    contracts_by_agent_filter,
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

# ============================================================================
# Универсальная выгрузка
# ============================================================================


def _export_simple(sql, params, name, headers, col_widths):
    """
    Универсальная выгрузка: выполняет SQL и собирает книгу из результата.

    Используется для выгрузок с простой структурой: один запрос,
    одна таблица. Для более сложных выгрузок (КДР, авансы) книги
    собираются отдельными функциями.

    Возвращает HttpResponse с готовым .xlsx.
    """
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return xlsx_response(
        make_wb(name, headers, col_widths, [[row[c] for c in cols] for row in rows]),
        name,
    )


# ============================================================================
# История изменений
# ============================================================================


@login_required
def export_history_status(request):
    """Выгрузка истории изменений статуса договора."""
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
            "Дата договора",
        ],
        [10, 40, 8, 50, 25, 25, 15, 50, 16, 16, 12, 12, 12],
    )


@login_required
def export_history_plan(request):
    """Выгрузка истории изменений плана."""
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
            "Дата договора",
        ],
        [10, 40, 8, 50, 15, 50, 16, 16, 14, 14, 12, 12],
    )


@login_required
def export_history_fact(request):
    """Выгрузка истории изменений факта."""
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
            "Дата договора",
        ],
        [10, 40, 8, 50, 15, 50, 16, 16, 12, 12],
    )


# ============================================================================
# Появившиеся договоры
# ============================================================================


# Заголовки и ширины колонок — общие для выгрузок
# «Новые заключённые» и «Новые незаключённые»
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
    """Выгрузка появившихся заключённых договоров."""
    sql, params = contracts_appeared("concluded")
    return _export_simple(
        sql, params, "новые_заключённые", APPEARED_HEADERS, APPEARED_WIDTHS
    )


@login_required
def export_appeared_not_concluded(request):
    """Выгрузка появившихся незаключённых договоров."""
    sql, params = contracts_appeared("not_concluded")
    return _export_simple(
        sql, params, "новые_незаключённые", APPEARED_HEADERS, APPEARED_WIDTHS
    )


# ============================================================================
# Дубликаты договоров
# ============================================================================


def _dupes_args(request):
    """Читает параметры фильтра дубликатов из GET-запроса (ЦФО и год)."""
    return request.GET.get("cfo", "").strip(), request.GET.get("year", "").strip()


@login_required
def export_contract_dupes(request):
    """
    Выгрузка дубликатов: полные повторы строк.

    Строки считаются дублями, если у них совпадают ИГК, контрагент,
    договор, предмет, заказ и этап графика.
    """
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
    """
    Выгрузка дубликатов по заказу.

    Группирует строки по ИГК, предмету и заказу: сколько строк,
    договоров и контрагентов попали в каждую группу.
    """
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


# ============================================================================
# КДР за год
# ============================================================================


@login_required
def export_kdr(request, year):
    """
    Выгрузка «Контроль договорной работы» за год.

    Структура отчёта:
    - По каждому ИГК: строка «Итого» по всем ЦФО + строки по каждому ЦФО
    - В конце строка «ИТОГО» по всем ИГК

    Необязательный период (start, end): если задан, считается количество
    договоров, заключённых за период (колонка «Заключено за период»).

    Типы строк (для подсветки в Excel):
    - "subtotal" — итог по ИГК
    - "normal" — обычная строка ЦФО
    - "total" — итог по всем ИГК
    """
    # Проверяем год — должен быть в списке YEARS
    yc = YEAR_COL.get(str(year))
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)

    # Период для колонки «Заключено за период» (необязательный)
    start_date = request.GET.get("start", "").strip()
    end_date = request.GET.get("end", "").strip()
    has_period = bool(start_date and end_date)
    if has_period and not (valid_date(start_date) and valid_date(end_date)):
        return JsonResponse({"error": "недопустимая дата периода"}, status=400)

    # Основной запрос: данные по каждому ЦФО внутри ИГК
    with connection.cursor() as cur:
        cur.execute(kdr_export(year))
        db_cols = [c[0] for c in cur.description]
        detail_rows = [dict(zip(db_cols, r)) for r in cur.fetchall()]

    # Если задан период — запрашиваем количество договоров, заключённых за период
    # Ключ: (последние 4 символа ИГК, ЦФО) -> количество
    delta_map = {}
    if has_period:
        delta_sql, delta_params = kdr_delta(yc, start_date, end_date)
        with connection.cursor() as cur:
            cur.execute(delta_sql, delta_params)
            for row in cur.fetchall():
                delta_map[(row[0], row[1])] = row[2]

    # --- Вспомогательные функции форматирования ---

    def fv(v):
        """Приводит значение к float, None -> 0."""
        return float(v or 0)

    def pct(a, b):
        """Процент a от b с одним знаком после запятой."""
        return round(fv(a) / fv(b) * 100, 1) if fv(b) else 0.0

    def igk4(s):
        """Последние 4 символа ИГК — ключ в delta_map."""
        return (s or "")[-4:]

    def row_vals(r, igk_label, cfo_label, d_igk, d_cfo, delta_value=None):
        """
        Собирает одну строку отчёта из агрегатов.

        Параметры:
        - r: словарь с агрегатами (total_count, concl_count, year_count и т.д.)
        - igk_label, cfo_label: подписи для первых двух колонок
        - d_igk, d_cfo: ключи для поиска delta в delta_map
        - delta_value: если задано, используется вместо поиска в delta_map
        """
        yn, ys = fv(r["year_count"]), fv(r["year_sum"])
        # Количество заключённых за период: из параметра или из delta_map
        if delta_value is not None:
            delta = delta_value
        else:
            delta = delta_map.get((igk4(d_igk), d_cfo), 0) if has_period else 0

        return [
            igk_label,  # ИГК
            cfo_label,  # ЦФО
            fv(r["total_count"]),  # Всего договоров, шт.
            fv(r["total_sum"]),  # Сумма всех договоров
            fv(r["concl_count"]),  # Заключено, шт.
            fv(r["concl_sum"]),  # Сумма заключённых
            fv(r["year_count"]),  # Всего на год, шт.
            fv(r["year_sum"]),  # Сумма на год
            fv(r["year_concl_count"]),  # Заключено на год, шт.
            pct(r["year_concl_count"], yn),  # % контрактации (по количеству)
            fv(r["year_concl_sum"]),  # Сумма заключённых на год
            pct(r["year_concl_sum"], ys),  # % контрактации (по сумме)
            delta,  # Заключено за период
            fv(r["year_not_concl_count"]),  # Не заключено, шт.
            fv(r["year_not_concl_sum"]),  # Сумма не заключённых
            fv(r["pp_plan"]),  # План аванса
            fv(r["pp_fact"]),  # Факт аванса
            pct(r["pp_fact"], r["pp_plan"]),  # % авансирования
        ]

    def sum_group(rows):
        """Суммирует агрегаты по списку строк (для итоговых строк)."""
        keys = [
            "total_count",
            "total_sum",
            "concl_count",
            "concl_sum",
            "year_count",
            "year_sum",
            "year_concl_count",
            "year_concl_sum",
            "delta_concl_count",
            "year_not_concl_count",
            "year_not_concl_sum",
            "pp_plan",
            "pp_fact",
        ]
        return {k: sum(fv(r[k]) for r in rows) for k in keys}

    # --- Группируем строки по ИГК ---
    igk_groups = defaultdict(list)
    for r in detail_rows:
        igk_groups[r["igk"]].append(r)

    # --- Собираем строки отчёта ---
    rows, kinds = [], []
    total_delta_sum = 0
    for igk, grp in igk_groups.items():
        # Считаем сумму заключённых за период по ИГК
        delta_sum = 0
        if has_period:
            for r in grp:
                delta_val = delta_map.get((igk4(r["igk"]), r["cfo"]), 0)
                if delta_val > 0:
                    delta_sum += delta_val
        total_delta_sum += delta_sum
        # Строка «Итого» по ИГК (агрегаты по всем ЦФО)
        rows.append(
            row_vals(sum_group(grp), igk, "Итого", igk, grp[0]["cfo"], delta_sum)
        )
        kinds.append("subtotal")
        # Строки по каждому ЦФО внутри ИГК
        for r in grp:
            rows.append(row_vals(r, "", r["cfo"], r["igk"], r["cfo"]))
            kinds.append("normal")

    # Строка «ИТОГО» по всем ИГК
    rows.append(row_vals(sum_group(detail_rows), "ИТОГО", "", "", "", total_delta_sum))
    kinds.append("total")

    # Форматируем даты периода для заголовка колонки
    if has_period:
        start_date = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d.%m.%Y")
        end_date = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d.%m.%Y")

    yy = str(year)
    period_text = f" с {start_date} по {end_date}" if has_period else ""

    # Заголовки колонок (включают год и период)
    headers = [
        "ИГК",
        "ЦФО",
        "Всего договоров, шт.",
        "Сумма всех договоров, млн.руб.",
        "Заключено, шт.",
        "Сумма заключенных договоров(Всех), млн.руб.",
        f"Всего договоров на {yy}г., шт.",
        f"Сумма договоров на {yy}г., млн.руб.",
        f"Заключено договоров на {yy}г., шт.",
        f"% контрактации {yy}г.",
        f"Сумма заключенных договоров на {yy}г., млн.руб.",
        f"% контрактации {yy}г.",
        f"Заключено{period_text}, шт.",
        "Не заключено, шт.",
        "Сумма не заключенных договоров, млн.руб.",
        f"Плановая сумма аванса в {yy}г., млн.руб.",
        f"Фактическая сумма аванса на {yy}г., млн.руб.",
        f"% авансирования на {yy}г.",
        "Примечание",
    ]
    # Числовые форматы колонок: денежные — с разделителями, проценты — с "%"
    formats = {
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
    col_w = [10, 6, 12, 14, 12, 16, 12, 14, 12, 12, 16, 14, 12, 16, 14, 14, 12, 16, 17]
    return xlsx_response(
        make_wb(f"КДР {year}", headers, col_w, rows, kinds, formats), f"кдр_{year}"
    )


# ============================================================================
# Авансы и договоры по контрагенту
# ============================================================================


@login_required
def export_advances(request, year):
    """
    Выгрузка авансов за год по шаблону.

    Собирается отдельной функцией в services/pivot.py,
    потому что структура сложнее обычной таблицы (сводная).
    """
    yc = YEAR_COL.get(str(year))
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)
    with connection.cursor() as cur:
        cur.execute(advances(year))
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return build_advances_xlsx(rows, str(year))


@login_required
def export_contracts_by_agent(request, year):
    """
    Выгрузка договоров по контрагенту за год.

    Контрагент передаётся через GET-параметр agent. Если не задан —
    выгружаются договоры по всем контрагентам.
    """
    yc = YEAR_COL.get(str(year))
    if not yc:
        return JsonResponse({"error": "недопустимый год"}, status=400)

    # Фильтр по контрагенту: строит условия и параметры для SQL
    agent = request.GET.get("agent", "").strip()
    conditions, params = contracts_by_agent_filter(yc, agent)
    sql = query_contracts_by_agent(conditions)

    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

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
    # Текстовые поля — идут первыми колонками без форматирования
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

    # Собираем строки: текстовые поля + числа (план, факт, остаток)
    data_rows = [
        [row[f] for f in txt_fld]
        + [float(row["plan"] or 0), float(row["fact"] or 0), float(row["remain"] or 0)]
        for row in rows
    ]
    # Безопасное имя контрагента для имени файла (без пробелов, до 30 символов)
    agent_safe = agent[:30].replace(" ", "_") if agent else ""
    return xlsx_response(
        make_wb(f"Договоры {year}", headers, col_w, data_rows),
        f'контрагент{"_" + agent_safe if agent_safe else ""}_{year}',
    )
