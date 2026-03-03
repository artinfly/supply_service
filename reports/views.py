from django.db.models import Count, Sum, Q, F, FloatField
from django.db.models.functions import Coalesce, Round
from django.http import JsonResponse
from django.db import connection
from datetime import date, timedelta
from reports.models import IgkStatData, DayData
from django.shortcuts import render

def index(request):
    return render(request, 'reports/index.html')

def kdr_table(request, year):
    api_name = f'kdr{year}'  # имя URL для API, должно совпадать с names в urls.py
    return render(request, 'reports/kdr_table.html', {'year': year, 'api_name': api_name})

def igk_concluded_table(request, year):
    api_name = f'igk_concluded_{year}'
    return render(request, 'reports/igk_table.html', {'year': year, 'api_name': api_name, 'status': 'Concluded'})

def igk_not_concluded_table(request, year):
    api_name = f'igk_not_concluded_{year}'
    return render(request, 'reports/igk_table.html', {'year': year, 'api_name': api_name, 'status': 'Not Concluded'})

def igk_terminated_table(request, year):
    api_name = f'igk_terminated_{year}'
    return render(request, 'reports/igk_table.html', {'year': year, 'api_name': api_name, 'status': 'Terminated'})

def day_stat_only_igk_table(request):
    return render(request, 'reports/day_stat_only_igk.html')

def day_stat_with_cfo_table(request):
    return render(request, 'reports/day_stat_with_cfo.html')

def all_pps_table(request):
    return render(request, 'reports/all_pps.html')

def all_contracts_table(request):
    return render(request, 'reports/all_contracts.html')

# ==================== KDR_STAT ====================

def kdr_stat_2025(request):
    return _kdr_stat_by_year(request, 'y25')

def kdr_stat_2026(request):
    return _kdr_stat_by_year(request, 'y26')

def kdr_stat_2027(request):
    return _kdr_stat_by_year(request, 'y27')

def _kdr_stat_by_year(request, year_field):
    year_filter = {year_field: True}
    queryset = IgkStatData.objects.values('igk').annotate(
        orders=Count('contract', distinct=True,
                     filter=Q(order__isnull=False) & ~Q(order='')),
        order_sum=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='')), 0.0) / 1000000.0,
            2
        ),
        count_concluded=Count('contract', distinct=True,
                              filter=Q(order__isnull=False) & ~Q(order='') &
                                     Q(status__in=['Заключен', 'Исполнен'])),
        concluded_order_sum=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(status__in=['Заключен', 'Исполнен'])), 0.0) / 1000000.0,
            2
        ),
        count_curr_year=Count('contract', distinct=True,
                              filter=Q(order__isnull=False) & ~Q(order='') &
                                     Q(**year_filter) & ~Q(status='Расторгнут')),
        order_sum_curr_year=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & ~Q(status='Расторгнут')), 0.0) / 1000000.0,
            2
        ),
        count_concluded_curr_year=Count('contract', distinct=True,
                                        filter=Q(order__isnull=False) & ~Q(order='') &
                                               Q(**year_filter) & Q(status__in=['Заключен', 'Исполнен'])),
        concluded_order_sum_curr_year=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(status__in=['Заключен', 'Исполнен'])), 0.0) / 1000000.0,
            2
        ),
        pp_sum_plan=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(payment_type='Аванс') & ~Q(status='Расторгнут')), 0.0) / 1000000.0,
            2
        ),
        pp_sum_fact=Round(
            Coalesce(Sum('fact', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(payment_type='Аванс') & ~Q(status='Расторгнут')), 0.0) / 1000000.0,
            2
        ),
        count_not_concluded_curr_year=Count('contract', distinct=True,
                                            filter=Q(order__isnull=False) & ~Q(order='') &
                                                   Q(**year_filter) & Q(status='Не заключен')),
        not_concluded_order_sum_curr_year=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(status='Не заключен')), 0.0) / 1000000.0,
            2
        ),
    )

    data = list(queryset)

    for row in data:
        if row['count_curr_year']:
            row['count_concluded_percent_curr_year'] = int(row['count_concluded_curr_year'] * 100 / row['count_curr_year'])
        else:
            row['count_concluded_percent_curr_year'] = 0

        if row['order_sum_curr_year']:
            row['order_sum_percent_curr_year'] = int(row['concluded_order_sum_curr_year'] * 100 / row['order_sum_curr_year'])
        else:
            row['order_sum_percent_curr_year'] = 0

        if row['pp_sum_plan']:
            row['pp_percent'] = int(row['pp_sum_fact'] * 100 / row['pp_sum_plan'])
        else:
            row['pp_percent'] = 0

    total = IgkStatData.objects.filter(**year_filter).aggregate(
        total_orders=Count('contract', distinct=True,
                           filter=Q(order__isnull=False) & ~Q(order='')),
        total_order_sum=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='')), 0.0) / 1000000.0,
            2
        ),
        total_count_concluded=Count('contract', distinct=True,
                                    filter=Q(order__isnull=False) & ~Q(order='') &
                                           Q(status__in=['Заключен', 'Исполнен'])),
        total_concluded_sum=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(status__in=['Заключен', 'Исполнен'])), 0.0) / 1000000.0,
            2
        ),
        total_count_curr_year=Count('contract', distinct=True,
                                    filter=Q(order__isnull=False) & ~Q(order='') &
                                           Q(**year_filter) & ~Q(status='Расторгнут')),
        total_order_sum_curr_year=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & ~Q(status='Расторгнут')), 0.0) / 1000000.0,
            2
        ),
        total_count_concluded_curr_year=Count('contract', distinct=True,
                                              filter=Q(order__isnull=False) & ~Q(order='') &
                                                     Q(**year_filter) & Q(status__in=['Заключен', 'Исполнен'])),
        total_concluded_sum_curr_year=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(status__in=['Заключен', 'Исполнен'])), 0.0) / 1000000.0,
            2
        ),
        total_pp_sum_plan=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(payment_type='Аванс') & ~Q(status='Расторгнут')), 0.0) / 1000000.0,
            2
        ),
        total_pp_sum_fact=Round(
            Coalesce(Sum('fact', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(payment_type='Аванс') & ~Q(status='Расторгнут')), 0.0) / 1000000.0,
            2
        ),
        total_count_not_concluded_curr_year=Count('contract', distinct=True,
                                                  filter=Q(order__isnull=False) & ~Q(order='') &
                                                         Q(**year_filter) & Q(status='Не заключен')),
        total_not_concluded_sum_curr_year=Round(
            Coalesce(Sum('plan', filter=Q(order__isnull=False) & ~Q(order='') &
                                    Q(**year_filter) & Q(status='Не заключен')), 0.0) / 1000000.0,
            2
        ),
    )

    if total['total_count_curr_year']:
        total['total_count_concluded_percent_curr_year'] = int(total['total_count_concluded_curr_year'] * 100 / total['total_count_curr_year'])
    else:
        total['total_count_concluded_percent_curr_year'] = 0

    if total['total_order_sum_curr_year']:
        total['total_order_sum_percent_curr_year'] = int(total['total_concluded_sum_curr_year'] * 100 / total['total_order_sum_curr_year'])
    else:
        total['total_order_sum_percent_curr_year'] = 0

    if total['total_pp_sum_plan']:
        total['total_pp_percent'] = int(total['total_pp_sum_fact'] * 100 / total['total_pp_sum_plan'])
    else:
        total['total_pp_percent'] = 0

    total_row = {
        'igk': 'ИТОГО',
        'orders': total['total_orders'],
        'order_sum': total['total_order_sum'],
        'count_concluded': total['total_count_concluded'],
        'concluded_order_sum': total['total_concluded_sum'],
        'count_curr_year': total['total_count_curr_year'],
        'order_sum_curr_year': total['total_order_sum_curr_year'],
        'count_concluded_curr_year': total['total_count_concluded_curr_year'],
        'concluded_order_sum_curr_year': total['total_concluded_sum_curr_year'],
        'pp_sum_plan': total['total_pp_sum_plan'],
        'pp_sum_fact': total['total_pp_sum_fact'],
        'count_not_concluded_curr_year': total['total_count_not_concluded_curr_year'],
        'not_concluded_order_sum_curr_year': total['total_not_concluded_sum_curr_year'],
        'count_concluded_percent_curr_year': total['total_count_concluded_percent_curr_year'],
        'order_sum_percent_curr_year': total['total_order_sum_percent_curr_year'],
        'pp_percent': total['total_pp_percent'],
    }

    data.append(total_row)
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False, 'indent': 2})

# ==================== IGK_STAT ====================

def igk_stat_concluded_2025(request):
    return _igk_stat_by_year_status(request, 'y25', ['Заключен', 'Исполнен'])

def igk_stat_concluded_2026(request):
    return _igk_stat_by_year_status(request, 'y26', ['Заключен', 'Исполнен'])

def igk_stat_concluded_2027(request):
    return _igk_stat_by_year_status(request, 'y27', ['Заключен', 'Исполнен'])

def igk_stat_not_concluded_2025(request):
    return _igk_stat_by_year_status(request, 'y25', ['Не заключен'])

def igk_stat_not_concluded_2026(request):
    return _igk_stat_by_year_status(request, 'y26', ['Не заключен'])

def igk_stat_not_concluded_2027(request):
    return _igk_stat_by_year_status(request, 'y27', ['Не заключен'])

def igk_stat_terminated_2025(request):
    return _igk_stat_by_year_status(request, 'y25', ['Расторгнут'])

def igk_stat_terminated_2026(request):
    return _igk_stat_by_year_status(request, 'y26', ['Расторгнут'])

def igk_stat_terminated_2027(request):
    return _igk_stat_by_year_status(request, 'y27', ['Расторгнут'])

def _igk_stat_by_year_status(request, year_field, status_list):
    year_filter = {year_field: True}
    base_filter = Q(**year_filter) & Q(status__in=status_list)

    queryset = IgkStatData.objects.filter(base_filter).values('igk').annotate(
        spec_sum=Coalesce(Sum('plan'), 0.0, output_field=FloatField()),
        pp_sum=Coalesce(Sum('plan', filter=Q(payment_type='Аванс')), 0.0, output_field=FloatField()),
        pp_fact=Coalesce(Sum('fact', filter=Q(payment_type='Аванс')), 0.0, output_field=FloatField()),
        pp_quantity=Count('pp_id', distinct=True)
    ).order_by('igk')

    data = []
    for item in queryset:
        row = {
            'igk': item['igk'],
            'spec_sum': round(item['spec_sum'], 2),
            'pp_sum': round(item['pp_sum'], 2),
            'pp_fact': round(item['pp_fact'], 2),
            'pp_quantity': item['pp_quantity'],
        }
        if item['spec_sum']:
            row['pp_percent'] = int(item['pp_sum'] * 100 / item['spec_sum'])
            row['fact_percent'] = int(item['pp_fact'] * 100 / item['spec_sum'])
            row['pp_remain'] = round(item['pp_sum'] - item['pp_fact'], 2)
            row['remain_percent'] = int((item['pp_sum'] - item['pp_fact']) * 100 / item['spec_sum'])
        else:
            row['pp_percent'] = 0
            row['fact_percent'] = 0
            row['pp_remain'] = 0
            row['remain_percent'] = 0
        data.append(row)

    # Итоговая строка
    total = IgkStatData.objects.filter(base_filter).aggregate(
        total_spec_sum=Coalesce(Sum('plan'), 0.0, output_field=FloatField()),
        total_pp_sum=Coalesce(Sum('plan', filter=Q(payment_type='Аванс')), 0.0, output_field=FloatField()),
        total_pp_fact=Coalesce(Sum('fact', filter=Q(payment_type='Аванс')), 0.0, output_field=FloatField()),
        total_pp_quantity=Count('pp_id', distinct=True)
    )

    total_row = {
        'igk': 'ИТОГО',
        'spec_sum': round(total['total_spec_sum'], 2),
        'pp_sum': round(total['total_pp_sum'], 2),
        'pp_fact': round(total['total_pp_fact'], 2),
        'pp_quantity': total['total_pp_quantity'],
    }
    if total['total_spec_sum']:
        total_row['pp_percent'] = int(total['total_pp_sum'] * 100 / total['total_spec_sum'])
        total_row['fact_percent'] = int(total['total_pp_fact'] * 100 / total['total_spec_sum'])
        total_row['pp_remain'] = round(total['total_pp_sum'] - total['total_pp_fact'], 2)
        total_row['remain_percent'] = int((total['total_pp_sum'] - total['total_pp_fact']) * 100 / total['total_spec_sum'])
    else:
        total_row['pp_percent'] = 0
        total_row['fact_percent'] = 0
        total_row['pp_remain'] = 0
        total_row['remain_percent'] = 0

    data.append(total_row)
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False, 'indent': 2})

# ==================== DAY_STAT ====================

def day_stat_only_igk(request):
    today = date.today()
    yesterday = today - timedelta(days=1)
    is_friday = today.weekday() == 4
    delta_day = today - timedelta(days=7) if is_friday else yesterday

    queryset = DayData.objects.filter(
        cfo__isnull=True,
        upload_date=today
    ).values('igk').annotate(
        orders_count=Coalesce(Sum('orders_count'), 0),
        orders_sum=Coalesce(Sum('orders_sum'), 0.0),
        concluded_orders_count=Coalesce(Sum('concluded_orders_count'), 0),
        concluded_orders_sum=Coalesce(Sum('concluded_orders_sum'), 0.0),
        not_concluded_orders_count=F('orders_count') - F('concluded_orders_count'),
        not_concluded_orders_sum=Round(
            F('orders_sum') - F('concluded_orders_sum'),
            2
        ),
    )

    data = list(queryset)
    for row in data:
        yesterday_data = DayData.objects.filter(
            igk=row['igk'],
            cfo__isnull=True,
            upload_date=delta_day
        ).aggregate(
            conc_orders=Coalesce(Sum('concluded_orders_count'), 0),
            conc_sum=Coalesce(Sum('concluded_orders_sum'), 0.0)
        )
        row['conc_orders_delta'] = row['concluded_orders_count'] - yesterday_data['conc_orders']
        row['conc_sum_delta'] = round(row['concluded_orders_sum'] - yesterday_data['conc_sum'], 2)

    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False, 'indent': 2})

def day_stat_with_cfo(request):
    today = date.today()
    yesterday = today - timedelta(days=1)
    is_friday = today.weekday() == 4
    delta_day = today - timedelta(days=7) if is_friday else yesterday

    queryset = DayData.objects.filter(
        cfo__isnull=False,
        upload_date=today
    ).values('igk', 'cfo').annotate(
        orders_count=Coalesce(Sum('orders_count'), 0),
        orders_sum=Coalesce(Sum('orders_sum'), 0.0),
        concluded_orders_count=Coalesce(Sum('concluded_orders_count'), 0),
        concluded_orders_sum=Coalesce(Sum('concluded_orders_sum'), 0.0),
        not_concluded_orders_count=F('orders_count') - F('concluded_orders_count'),
        not_concluded_orders_sum=Round(
            F('orders_sum') - F('concluded_orders_sum'),
            2
        ),
    )

    data = list(queryset)
    for row in data:
        yesterday_data = DayData.objects.filter(
            igk=row['igk'],
            cfo=row['cfo'],
            upload_date=delta_day
        ).aggregate(
            conc_orders=Coalesce(Sum('concluded_orders_count'), 0),
            conc_sum=Coalesce(Sum('concluded_orders_sum'), 0.0)
        )
        row['conc_orders_delta'] = row['concluded_orders_count'] - yesterday_data['conc_orders']
        row['conc_sum_delta'] = round(row['concluded_orders_sum'] - yesterday_data['conc_sum'], 2)

    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False, 'indent': 2})

# ==================== ALL PPs и ALL Contracts ====================

def all_pps(request):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                igk, c_agent, cfo, contract, status, payment_type, item, "order", 
                y25, y26, y27, stage,
                ROUND(CAST(SUM(plan) OVER (PARTITION BY igk, contract, payment_type, "order", stage) AS numeric), 2) AS SpecSum,
                ROUND(CAST(SUM(plan) OVER (PARTITION BY igk, contract, payment_type, "order", stage) AS numeric), 2) AS PPSum,
                CASE 
                    WHEN SUM(plan) OVER (PARTITION BY igk, contract, payment_type, "order", stage) = 0 THEN 0
                    ELSE ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) OVER (PARTITION BY igk, contract, "order", stage) * 100.0 / 
                               SUM(plan) OVER (PARTITION BY igk, contract, payment_type, "order", stage) AS numeric), 0)
                END AS PP_Percent,
                ROUND(CAST(SUM(fact) OVER (PARTITION BY igk, contract, payment_type, "order", stage) AS numeric), 2) AS PPFact,
                ROUND(CAST(SUM(fact) OVER (PARTITION BY igk, contract, "order") * 100.0 / 
                      NULLIF(SUM(plan) OVER (PARTITION BY igk, contract, "order"), 0) AS numeric), 0) AS Fact_Percent,
                ROUND(CAST(SUM(plan) OVER (PARTITION BY igk, contract, "order") - 
                      SUM(fact) OVER (PARTITION BY igk, contract, "order") AS numeric), 2) AS PPRemain,
                ROUND(CAST((SUM(plan) OVER (PARTITION BY igk, contract, "order") - 
                      SUM(fact) OVER (PARTITION BY igk, contract, "order")) * 100.0 / 
                      NULLIF(SUM(plan) OVER (PARTITION BY igk, contract, "order"), 0) AS numeric), 0) AS Remain_Perce,
                pp_id,
                plan_date
            FROM "dbo"."igk_stat_data"
            ORDER BY igk
        """)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False, 'indent': 2})

def all_contracts(request):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                igk, c_agent, contract, status, 
                COALESCE(payment_type, 'ИНОЕ') AS payment_type,
                item, "order", stage, y25, y26, y27,
                ROUND(CAST(SUM(plan) AS numeric), 2) AS SpecSum,
                ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN plan ELSE 0 END) AS numeric), 2) AS PPSum,
                ROUND(CAST(SUM(CASE WHEN payment_type = 'Аванс' THEN fact ELSE 0 END) AS numeric), 2) AS PPFact,
                ROUND(CAST(SUM(plan) - SUM(fact) AS numeric), 2) AS PPRemain
            FROM "dbo"."igk_stat_data"
            GROUP BY GROUPING SETS (
                (igk, c_agent, contract, payment_type, item, "order", stage, y25, y26, y27, status),
                (c_agent, contract, igk, "order", y25, y26, y27, item, status)
            )
        """)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False, 'indent': 2})