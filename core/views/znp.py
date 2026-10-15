"""Страницы по заявкам на платёж (ЗнП): сводки и реестры ФЗД и SAP.

ФЗД — заявки из системы ФЗД, привязаны к позициям договоров (ZnpData.parent).
SAP — заявки из SAP, хранятся отдельно (ZnpDataSAP), к договорам не привязаны.
Реестры отдают только каркас страницы, строки грузятся из api_znp_list /
api_znp_sap_list.
"""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Exists, OuterRef
from django.db.models.expressions import RawSQL
from django.shortcuts import render
from django.utils import timezone

from ..models import IgkStatData, NsiIgk, SystemEvent, ZnpData, ZnpDataSAP
from ..services.dashboards.cards import (
    EMPTY_NOT_ISSUED,
    EMPTY_SAP,
    EMPTY_STAGES,
    EMPTY_ZNP,
    ZNP_STAGE_LABELS,
    ZNP_STAGE_NAMES,
    breakdown_from_stats,
    cfo_breakdown_row,
    filter_by_year,
    not_issued_aggregates,
    sap_aggregates,
    sap_cards,
    stage_aggregates,
    znp_aggregates,
)
from ..services.dashboards.sap_status import (
    SAP_STAGE_NAMES,
    SAP_STAGE_PARAMS,
    sap_second_date,
)
from ..services.queries import (
    CONCLUDED,
    SAP_CFO,
    YEARS,
    distinct_sap_cfo,
    distinct_sap_igk,
    needs_znp,
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
    """Сводка по заявкам ФЗД: карточки (всего и за год) и таблица по ЦФО.

    Учитываются только позиции заключённых договоров. «Не оформлено» —
    позиции без заявки, у которых остаток больше допуска (needs_znp).
    """
    available_igk = NsiIgk.objects.all()
    year = valid_year(request.GET.get("year"))
    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = base_context()
    has_znp = Exists(ZnpData.objects.filter(parent=OuterRef("pk")))

    # Позиции заключённых договоров, по которым заявки ещё нет, а она нужна
    def _not_issued_qs(igk=None):
        qs = (
            IgkStatData.objects.filter(status__in=CONCLUDED)
            .annotate(has_znp=has_znp)
            .filter(has_znp=False)
            .annotate(needs_znp=RawSQL(needs_znp("igk_stat_data"), []))
            .filter(needs_znp=True)
        )
        if igk is not None:
            qs = qs.filter(igk=igk)
        return qs

    # Заявки, привязанные к позициям заключённых договоров
    def _znp_qs(igk=None):
        qs = ZnpData.objects.filter(parent__status__in=CONCLUDED)
        if igk is not None:
            qs = qs.filter(parent__igk=igk)
        return qs

    # Все позиции заключённых договоров (знаменатель для процентов)
    def _stages_qs(igk=None):
        qs = IgkStatData.objects.filter(status__in=CONCLUDED)
        if igk is not None:
            qs = qs.filter(igk=igk)
        return qs

    all_not_issued_qs = _not_issued_qs()
    all_znp_qs = _znp_qs()
    all_stages_qs = _stages_qs()

    year_not_issued_qs = filter_by_year(all_not_issued_qs, year)
    year_znp_qs = filter_by_year(all_znp_qs, year, field_prefix="parent__")
    year_stages_qs = filter_by_year(all_stages_qs, year)

    def _breakdown(not_issued_qs, znp_qs, stages_qs):
        return breakdown_from_stats(
            not_issued_qs.aggregate(**not_issued_aggregates()),
            znp_qs.aggregate(**znp_aggregates()),
            stages_qs.aggregate(**stage_aggregates()),
        )

    all_breakdown = _breakdown(all_not_issued_qs, all_znp_qs, all_stages_qs)
    year_breakdown = _breakdown(year_not_issued_qs, year_znp_qs, year_stages_qs)

    available_cfo = list(
        IgkStatData.objects.filter(igk=selected_igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )

    igk_not_issued_qs = filter_by_year(_not_issued_qs(igk=selected_igk), year)
    igk_znp_qs = filter_by_year(
        _znp_qs(igk=selected_igk), year, field_prefix="parent__"
    )
    igk_stages_qs = filter_by_year(_stages_qs(igk=selected_igk), year)

    not_issued_stats = {
        row["cfo"]: row
        for row in igk_not_issued_qs.values("cfo").annotate(**not_issued_aggregates())
    }
    znp_stats = {
        row["parent__cfo"]: row
        for row in igk_znp_qs.values("parent__cfo").annotate(**znp_aggregates())
    }
    stage_stats = {
        row["cfo"]: row
        for row in igk_stages_qs.values("cfo").annotate(**stage_aggregates())
    }

    cfo_table = [
        cfo_breakdown_row(
            cfo,
            breakdown_from_stats(
                not_issued_stats.get(cfo, EMPTY_NOT_ISSUED),
                znp_stats.get(cfo, EMPTY_ZNP),
                stage_stats.get(cfo, EMPTY_STAGES),
            ),
            ZNP_STAGE_LABELS,
        )
        for cfo in available_cfo
    ]

    cfo_total_row = cfo_breakdown_row(
        "ИТОГО",
        _breakdown(igk_not_issued_qs, igk_znp_qs, igk_stages_qs),
        ZNP_STAGE_LABELS,
    )

    chart_start = request.GET.get("start", "").strip()
    chart_end = request.GET.get("end", "").strip()

    if not (valid_date(chart_start) and valid_date(chart_end)):
        chart_start = chart_end = ""

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
    ctx = base_context()
    qs = ZnpDataSAP.objects.filter(cfo__in=SAP_CFO)

    def _breakdown(queryset, date=None):
        return sap_cards(queryset.aggregate(**sap_aggregates(date)))

    all_breakdown = _breakdown(qs)

    date_param = request.GET.get("date", "")
    first_date = (
        datetime.strptime(date_param, "%Y-%m-%d").date()
        if valid_date(date_param)
        else timezone.localdate()
    )
    second_date = sap_second_date(first_date)

    first_date_breakdown = _breakdown(qs, first_date)
    second_date_breakdown = _breakdown(qs, second_date)

    available_igk = list(
        qs.exclude(igk__isnull=True)
        .exclude(igk="")
        .values_list("igk", flat=True)
        .distinct()
        .order_by("igk")
    )
    selected_igk = request.GET.get("igk", "") or (
        available_igk[0] if available_igk else ""
    )

    cfo_qs = qs.filter(igk=selected_igk) if selected_igk else qs
    available_cfo = list(
        cfo_qs.values_list("cfo", flat=True).distinct().order_by("cfo")
    )
    cfo_stats = {
        row["cfo"]: row for row in cfo_qs.values("cfo").annotate(**sap_aggregates())
    }

    cfo_table = [
        cfo_breakdown_row(
            cfo,
            sap_cards(cfo_stats.get(cfo, EMPTY_SAP)),
            SAP_STAGE_PARAMS,
        )
        for cfo in available_cfo
    ]
    cfo_total_row = cfo_breakdown_row("ИТОГО", _breakdown(cfo_qs), SAP_STAGE_PARAMS)

    ctx.update(
        {
            "stage_names": SAP_STAGE_NAMES,
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "all": all_breakdown,
            "first_date": first_date,
            "second_date": second_date,
            "first_date_breakdown": first_date_breakdown,
            "second_date_breakdown": second_date_breakdown,
            "cfo_table": cfo_table,
            "cfo_total_row": cfo_total_row,
            "has_data": all_breakdown["total_count"] > 0,
            "no_data_hint": "Заявки на платёж из SAP ещё не загружены. Нужен файл выгрузки ЗнП (SAP).",
        }
    )

    # Время последней загрузки SAP — для надписи «Актуально на …»
    sap_load_event = SystemEvent.objects.filter(event_key="sap_load").first()
    ctx["sap_load_time"] = sap_load_event.event_time if sap_load_event else None

    return render(request, "znp_sap_table.html", ctx)
