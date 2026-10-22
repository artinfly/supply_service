"""Сводки по заявкам на платёж: ФЗД (привязаны к договорам) и SAP.

ФЗД: учитываются только позиции заключённых договоров. «Не оформлено» —
позиции без заявки, у которых остаток больше допуска (needs_znp).
"""

from django.db.models import Exists, OuterRef
from django.db.models.expressions import RawSQL

from ...models import IgkStatData, ZnpData, ZnpDataSAP
from ..queries import CONCLUDED, SAP_CFO, needs_znp
from .cards import (
    EMPTY_NOT_ISSUED,
    EMPTY_SAP,
    EMPTY_STAGES,
    EMPTY_ZNP,
    ZNP_STAGE_LABELS,
    breakdown_from_stats,
    cfo_breakdown_row,
    filter_by_year,
    not_issued_aggregates,
    sap_aggregates,
    sap_cards,
    stage_aggregates,
    znp_aggregates,
)
from .sap_status import SAP_STAGE_PARAMS

# --- ФЗД ---


def _not_issued_qs(igk=None):
    """Позиции заключённых договоров, по которым заявки ещё нет, а она нужна."""
    qs = (
        IgkStatData.objects.filter(status__in=CONCLUDED)
        .annotate(has_znp=Exists(ZnpData.objects.filter(parent=OuterRef("pk"))))
        .filter(has_znp=False)
        .annotate(needs_znp=RawSQL(needs_znp("igk_stat_data"), []))
        .filter(needs_znp=True)
    )
    return qs if igk is None else qs.filter(igk=igk)


def _znp_qs(igk=None):
    """Заявки, привязанные к позициям заключённых договоров."""
    qs = ZnpData.objects.filter(parent__status__in=CONCLUDED)
    return qs if igk is None else qs.filter(parent__igk=igk)


def _stages_qs(igk=None):
    """Все позиции заключённых договоров (знаменатель для процентов)."""
    qs = IgkStatData.objects.filter(status__in=CONCLUDED)
    return qs if igk is None else qs.filter(igk=igk)


def _year_querysets(year, igk=None):
    """Три выборки (не оформлено, заявки, позиции) за год, при необходимости по ИГК."""
    return (
        filter_by_year(_not_issued_qs(igk), year),
        filter_by_year(_znp_qs(igk), year, field_prefix="parent__"),
        filter_by_year(_stages_qs(igk), year),
    )


def _breakdown(not_issued_qs, znp_qs, stages_qs):
    """Карточки по трём выборкам."""
    return breakdown_from_stats(
        not_issued_qs.aggregate(**not_issued_aggregates()),
        znp_qs.aggregate(**znp_aggregates()),
        stages_qs.aggregate(**stage_aggregates()),
    )


def znp_breakdowns(year):
    """Карточки ФЗД за всё время и за выбранный год."""
    return (
        _breakdown(_not_issued_qs(), _znp_qs(), _stages_qs()),
        _breakdown(*_year_querysets(year)),
    )


def znp_cfo_table(igk, year):
    """Строки по ЦФО выбранного ИГК за год и строка «ИТОГО»."""
    not_issued_qs, znp_qs, stages_qs = _year_querysets(year, igk)
    not_issued = {
        row["cfo"]: row
        for row in not_issued_qs.values("cfo").annotate(**not_issued_aggregates())
    }
    znp = {
        row["parent__cfo"]: row
        for row in znp_qs.values("parent__cfo").annotate(**znp_aggregates())
    }
    stages = {
        row["cfo"]: row
        for row in stages_qs.values("cfo").annotate(**stage_aggregates())
    }
    available_cfo = (
        IgkStatData.objects.filter(igk=igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )
    rows = [
        cfo_breakdown_row(
            cfo,
            breakdown_from_stats(
                not_issued.get(cfo, EMPTY_NOT_ISSUED),
                znp.get(cfo, EMPTY_ZNP),
                stages.get(cfo, EMPTY_STAGES),
            ),
            ZNP_STAGE_LABELS,
        )
        for cfo in available_cfo
    ]
    total = cfo_breakdown_row(
        "ИТОГО", _breakdown(not_issued_qs, znp_qs, stages_qs), ZNP_STAGE_LABELS
    )
    return rows, total


# --- SAP ---


def sap_queryset():
    """Заявки SAP по ЦФО, которые учитываются в сводке."""
    return ZnpDataSAP.objects.filter(cfo__in=SAP_CFO)


def sap_breakdown(date=None):
    """Карточки SAP за всё время или за дату."""
    return sap_cards(sap_queryset().aggregate(**sap_aggregates(date)))


def sap_igk_list():
    """ИГК, встречающиеся в заявках SAP, по порядку."""
    return list(
        sap_queryset()
        .exclude(igk__isnull=True)
        .exclude(igk="")
        .values_list("igk", flat=True)
        .distinct()
        .order_by("igk")
    )


def sap_cfo_table(igk):
    """Строки по ЦФО (по выбранному ИГК или по всем) и строка «ИТОГО»."""
    qs = sap_queryset()
    if igk:
        qs = qs.filter(igk=igk)
    stats = {row["cfo"]: row for row in qs.values("cfo").annotate(**sap_aggregates())}
    available_cfo = qs.values_list("cfo", flat=True).distinct().order_by("cfo")
    rows = [
        cfo_breakdown_row(cfo, sap_cards(stats.get(cfo, EMPTY_SAP)), SAP_STAGE_PARAMS)
        for cfo in available_cfo
    ]
    total = cfo_breakdown_row(
        "ИТОГО", sap_cards(qs.aggregate(**sap_aggregates())), SAP_STAGE_PARAMS
    )
    return rows, total
