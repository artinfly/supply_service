"""Страницы по заявкам на платёж (ЗнП): сводки и реестры ФЗД и SAP.

ФЗД — заявки из системы ФЗД, привязаны к позициям договоров (ZnpData.parent).
SAP — заявки из SAP, хранятся отдельно (ZnpDataSAP), к договорам не привязаны.
Реестры отдают только каркас страницы, строки грузятся из api_znp_list /
api_znp_sap_list.
"""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.shortcuts import render
from django.utils import timezone

from ..models import NsiIgk, SystemEvent
from ..services.dashboards import znp as znp_cards
from ..services.dashboards.cards import ZNP_STAGE_NAMES
from ..services.dashboards.sap_status import SAP_STAGE_NAMES, sap_second_date
from ..services.queries import (
    YEARS,
    distinct_sap_cfo,
    distinct_sap_igk,
    valid_date,
    valid_year,
)
from .common import base_context, igk_and_cfo_lists


# --- Реестры ---


@login_required
def znp_list_table(request):
    """Реестр заявок на платёж (ФЗД)."""
    igk_list, cfo_list = igk_and_cfo_lists()
    ctx = base_context()
    ctx.update({"igk_list": igk_list, "cfo_list": cfo_list})
    return render(request, "znp_list.html", ctx)


@login_required
def znp_sap_list_table(request):
    """Реестр заявок на платёж (SAP)."""
    with connection.cursor() as cur:
        cur.execute(distinct_sap_igk())
        igk_list = [r[0] for r in cur.fetchall()]
        cur.execute(distinct_sap_cfo())
        cfo_list = [r[0] for r in cur.fetchall()]

    ctx = base_context()
    ctx.update({"igk_list": igk_list, "cfo_list": cfo_list})
    return render(request, "znp_sap_list.html", ctx)


# --- Сводки ---


@login_required
def znp_table(request):
    """Сводка по заявкам ФЗД: карточки (всего и за год) и таблица по ЦФО."""
    available_igk = NsiIgk.objects.all()
    year = valid_year(request.GET.get("year"))
    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    all_breakdown, year_breakdown = znp_cards.znp_breakdowns(year)
    cfo_table, cfo_total_row = znp_cards.znp_cfo_table(selected_igk, year)

    # Период графика оплат: оба конца или ни одного
    chart_start = request.GET.get("start", "").strip()
    chart_end = request.GET.get("end", "").strip()
    if not (valid_date(chart_start) and valid_date(chart_end)):
        chart_start = chart_end = ""

    ctx = base_context()
    ctx.update(
        {
            "available_years": YEARS,
            "selected_year": str(year),
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "chart_start": chart_start,
            "chart_end": chart_end,
            "stage_names": ZNP_STAGE_NAMES,
            "all": all_breakdown,
            "year": year_breakdown,
            "cfo_table": cfo_table,
            "cfo_total_row": cfo_total_row,
            "has_data": all_breakdown["total_count"] > 0,
            "no_data_hint": "Нет ни договоров, ни заявок на платёж (ФЗД). Нужны файлы выгрузки.",
        }
    )
    return render(request, "znp_table.html", ctx)


@login_required
def znp_sap_table(request):
    """Сводка по заявкам SAP: карточки за всё время и за две даты, таблица по ЦФО.

    Вторая дата — предыдущий рабочий день от выбранной (sap_second_date).
    """
    date_param = request.GET.get("date", "")
    first_date = (
        datetime.strptime(date_param, "%Y-%m-%d").date()
        if valid_date(date_param)
        else timezone.localdate()
    )
    second_date = sap_second_date(first_date)

    available_igk = znp_cards.sap_igk_list()
    selected_igk = request.GET.get("igk", "") or (available_igk[0] if available_igk else "")
    all_breakdown = znp_cards.sap_breakdown()
    cfo_table, cfo_total_row = znp_cards.sap_cfo_table(selected_igk)

    # Время последней загрузки SAP — для надписи «Актуально на …»
    sap_load_event = SystemEvent.objects.filter(event_key="sap_load").first()

    ctx = base_context()
    ctx.update(
        {
            "stage_names": SAP_STAGE_NAMES,
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "all": all_breakdown,
            "first_date": first_date,
            "second_date": second_date,
            "first_date_breakdown": znp_cards.sap_breakdown(first_date),
            "second_date_breakdown": znp_cards.sap_breakdown(second_date),
            "cfo_table": cfo_table,
            "cfo_total_row": cfo_total_row,
            "has_data": all_breakdown["total_count"] > 0,
            "no_data_hint": "Заявки на платёж из SAP ещё не загружены. Нужен файл выгрузки ЗнП (SAP).",
            "sap_load_time": sap_load_event.event_time if sap_load_event else None,
        }
    )
    return render(request, "znp_sap_table.html", ctx)
