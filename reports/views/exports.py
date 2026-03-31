from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse

from ..services.queries import (
    CONCLUDED, YEAR_COL,
    history_status, history_plan, history_fact,
    contract_dupes, kdr_export, kdr_delta, advances,
    export_contracts_by_agent as query_contracts_by_agent,
)
from ..services.excel import make_wb, xlsx_response
from ..services.pivot import build_advances_xlsx


def _export_simple(sql, params, name, headers, col_widths):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return xlsx_response(make_wb(name, headers, col_widths, [[row[c] for c in cols] for row in rows]), name)


@login_required
def export_history_status(request):
    return _export_simple(history_status(), [], 'история_статусов',
        ['ИГК', 'Контрагент', 'ЦФО', 'Договор', 'Статус (было)', 'Статус (стало)',
         'Тип платежа', 'Предмет', 'План, руб.', 'Факт, руб.',
         'Дата изменения', 'Дата загрузки', 'Дата договора'],
        [10, 40, 8, 50, 25, 25, 15, 50, 16, 16, 12, 12, 12])


@login_required
def export_history_plan(request):
    return _export_simple(history_plan(), [], 'история_плана',
        ['ИГК', 'Контрагент', 'ЦФО', 'Договор', 'Тип платежа', 'Предмет',
         'План (было), руб.', 'План (стало), руб.', 'Дата изменения', 'Дата договора'],
        [10, 40, 8, 50, 15, 50, 16, 16, 12, 12])


@login_required
def export_history_fact(request):
    return _export_simple(history_fact(), [], 'история_факта',
        ['ИГК', 'Контрагент', 'ЦФО', 'Договор', 'Тип платежа', 'Предмет',
         'Факт (было), руб.', 'Факт (стало), руб.', 'Дата изменения', 'Дата договора'],
        [10, 40, 8, 50, 15, 50, 16, 16, 12, 12])


@login_required
def export_contract_dupes(request):
    return _export_simple(contract_dupes(), [], 'дубли_договоров',
        ['Контрагент', 'Договор', 'Предмет', 'Заказ', 'Этап', 'Дата плана', 'Хеш'],
        [40, 50, 50, 20, 15, 12, 12])


@login_required
def export_kdr(request, year):
    yc = YEAR_COL.get(str(year))
    if not yc:
        return JsonResponse({'error': 'invalid year'}, status=400)

    start_date = request.GET.get('start', '').strip()
    end_date = request.GET.get('end', '').strip()
    has_period = bool(start_date and end_date)

    sql = kdr_export(year)
    params = []

    with connection.cursor() as cur:
        cur.execute(sql, params)
        db_cols = [c[0] for c in cur.description]
        detail_rows = [dict(zip(db_cols, r)) for r in cur.fetchall()]

    delta_map = {}
    if has_period:
        delta_sql, delta_params = kdr_delta(yc, start_date, end_date)
        with connection.cursor() as cur:
            cur.execute(delta_sql, delta_params)
            for row in cur.fetchall():
                delta_map[(row[0], row[1])] = row[2]

    def fv(v):
        return float(v or 0)

    def pct(a, b):
        return round(fv(a) / fv(b) * 100, 1) if fv(b) else 0.0

    def row_vals(r, igk_label, cfo_label, d_igk='', d_cfo=''):
        yn, ys = fv(r['year_count']), fv(r['year_sum'])
        delta = delta_map.get((d_igk, d_cfo), 0) if has_period else 0
        return [
            igk_label, cfo_label,
            fv(r['total_count']), fv(r['total_sum']),
            fv(r['concl_count']), fv(r['concl_sum']),
            fv(r['year_count']), fv(r['year_sum']),
            fv(r['year_concl_count']), pct(r['year_concl_count'], yn),
            fv(r['year_concl_sum']), pct(r['year_concl_sum'], ys),
            fv(r['year_not_concl_count']), fv(r['year_not_concl_sum']),
            fv(r['pp_plan']), fv(r['pp_fact']),
            pct(r['pp_fact'], r['pp_plan']),
            delta,
        ]

    def sum_group(rows):
        keys = [
            'total_count', 'total_sum', 'concl_count', 'concl_sum',
            'year_count', 'year_sum', 'year_concl_count', 'year_concl_sum',
            'year_not_concl_count', 'year_not_concl_sum',
            'pp_plan', 'pp_fact', 'delta_concl_count',
        ]
        return {k: sum(fv(r[k]) for r in rows) for k in keys}

    igk_groups = defaultdict(list)
    for r in detail_rows:
        igk_groups[r['igk']].append(r)

    rows, kinds = [], []
    for igk, grp in igk_groups.items():
        rows.append(row_vals(sum_group(grp), igk, 'Итого', igk, grp[0]['cfo']))
        kinds.append('subtotal')
        for r in grp:
            rows.append(row_vals(r, '', r['cfo'], r['igk'], r['cfo']))
            kinds.append('normal')
    rows.append(row_vals(sum_group(detail_rows), 'ИТОГО', '', '', ''))
    kinds.append('total')

    yy = str(year)[2:]
    period_text = f"({start_date} - {end_date})" if has_period else ""

    headers = [
        'ИГК', 'ЦФО',
        'Всего дог., шт.', 'Сумма всего, млн',
        'Заключено, шт.', 'Сумма заключённых, млн',
        f'Дог. {yy}г., шт.', f'Сумма {yy}г., млн',
        f'Заключено {yy}г., шт.', f'% конт. {yy}г. (шт.)',
        f'Сумма зак. {yy}г., млн', f'% конт. {yy}г. (сумма)',
        f'Не зак. {yy}г., шт.', f'Сумма незак. {yy}г., млн',
        f'АП план {yy}г., млн', f'АП факт {yy}г., млн',
        f'% АП {yy}г.',
        f'Закл. {period_text} шт.',
    ]
    col_w = [10, 6, 12, 14, 12, 16, 12, 14, 12, 12, 16, 14, 12, 16, 14, 14, 12, 16]
    return xlsx_response(make_wb(f'КДР {year}', headers, col_w, rows, kinds), f'кдр_{year}')


@login_required
def export_advances(request, year):
    yc = YEAR_COL.get(str(year))
    if not yc:
        return JsonResponse({'error': 'invalid year'}, status=400)
    with connection.cursor() as cur:
        cur.execute(advances(year))
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return build_advances_xlsx(rows, str(year))


@login_required
def export_contracts_by_agent(request, year):
    yc = YEAR_COL.get(str(year))
    if not yc:
        return JsonResponse({'error': 'invalid year'}, status=400)

    agent = request.GET.get('agent', '').strip()
    conditions = [
        f"{yc}=TRUE", "is_deleted=FALSE",
        "contract IS NOT NULL AND TRIM(contract)!=''",
        "payment_type IS NOT NULL AND TRIM(payment_type)!=''",
    ]
    params = []
    if agent:
        conditions.append("c_agent ILIKE %s")
        params.append(f'%{agent}%')

    sql, params = query_contracts_by_agent(year, conditions, params)

    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    headers = ['ИГК', 'Контрагент', 'ЦФО', 'Договор', 'Состояние', 'Тип платежа',
               'Предмет', 'Заказ', 'Этап', f'План {year}, руб.', f'Факт {year}, руб.', 'Остаток, руб.']
    col_w = [15, 40, 8, 50, 20, 15, 50, 20, 15, 18, 18, 18]
    txt_fld = ['igk', 'c_agent', 'cfo', 'contract', 'status', 'payment_type', 'item', 'order', 'stage']

    data_rows = [
        [row[f] for f in txt_fld] + [float(row['plan'] or 0), float(row['fact'] or 0), float(row['remain'] or 0)]
        for row in rows
    ]
    agent_safe = agent[:30].replace(' ', '_') if agent else ''
    return xlsx_response(
        make_wb(f'Договоры {year}', headers, col_w, data_rows),
        f'контрагент{"_" + agent_safe if agent_safe else ""}_{year}'
    )