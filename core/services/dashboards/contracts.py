"""Сводка «Договорная работа»: карточки и таблица по ЦФО.

Количество договоров везде — число РАЗНЫХ номеров договоров (distinct),
суммы — сумма плана по позициям.
"""

from django.db.models import Count, Q, Sum

from ...models import IgkStatData
from ..queries import ADVANCE, CONCLUDED, NOT_CONCL, TERMINATED
from .cards import EMPTY_CFO_STATS, cfo_row, cfo_totals_row, percent, to_mln

# Позиция договора считается, только если у неё заполнен номер заказа
HAS_ORDER_Q = Q(order__isnull=False) & ~Q(order__regex=r"^\s*$")

CONCLUDED_Q = Q(status__in=CONCLUDED)
NOT_CONCL_Q = Q(status__in=NOT_CONCL)
ADVANCE_Q = Q(payment_type=ADVANCE)


def _year_field(year):
    """Имя флага года: 2025 -> «y25»."""
    return f"y{str(year)[-2:]}"


def total_cards():
    """Карточки «Всего»: все позиции с заказом, включая расторгнутые."""
    totals = IgkStatData.objects.filter(HAS_ORDER_Q, contract__isnull=False).aggregate(
        count=Count("contract", distinct=True),
        plan_sum=Sum("plan"),
        concluded_count=Count("contract", filter=CONCLUDED_Q, distinct=True),
        concluded_plan=Sum("plan", filter=CONCLUDED_Q),
        not_concluded_count=Count("contract", filter=NOT_CONCL_Q, distinct=True),
        not_concluded_plan=Sum("plan", filter=NOT_CONCL_Q),
    )
    return {
        "all_contracts_count": totals["count"],
        "all_contracts_sum": to_mln(totals["plan_sum"]),
        "all_concluded_count": totals["concluded_count"],
        "all_concluded_sum": to_mln(totals["concluded_plan"]),
        "all_not_concluded_count": totals["not_concluded_count"],
        "all_not_concluded_sum": to_mln(totals["not_concluded_plan"]),
    }


def year_cards(year):
    """Карточки «За год»: позиции выбранного года без расторгнутых."""
    totals = (
        IgkStatData.objects.exclude(status__in=TERMINATED)
        .filter(HAS_ORDER_Q, contract__isnull=False, **{_year_field(year): True})
        .aggregate(
            count=Count("contract", distinct=True),
            plan_sum=Sum("plan"),
            concluded_count=Count("contract", filter=CONCLUDED_Q, distinct=True),
            concluded_plan=Sum("plan", filter=CONCLUDED_Q),
            advance_plan=Sum("plan", filter=ADVANCE_Q),
            advance_fact=Sum("fact", filter=ADVANCE_Q),
        )
    )
    count = totals["count"]
    concluded_count = totals["concluded_count"]
    plan = totals["plan_sum"] or 0
    concluded_plan = totals["concluded_plan"] or 0
    advance_plan = totals["advance_plan"] or 0
    advance_fact = totals["advance_fact"] or 0
    return {
        "curr_year_contracts_count": count,
        "curr_year_contracts_sum": to_mln(plan),
        "curr_year_concluded_count": concluded_count,
        "curr_year_concluded_sum": to_mln(concluded_plan),
        # «Не заключено за год» = всё за год (без расторгнутых) минус заключённые
        "curr_year_not_concluded_count": count - concluded_count,
        "curr_year_not_concluded_sum": to_mln(plan - concluded_plan),
        "curr_year_fact": to_mln(advance_fact),
        "curr_year_plan": to_mln(advance_plan),
        "curr_year_percent_count": percent(concluded_count, count),
        "curr_year_percent_sum": percent(concluded_plan, plan),
        "curr_year_percent_prepaid": percent(advance_fact, advance_plan),
    }


def cfo_table(igk, year):
    """Строки таблицы по ЦФО выбранного ИГК и строка «ИТОГО» в конце."""
    year_q = Q(**{_year_field(year): True})
    available_cfo = (
        IgkStatData.objects.filter(igk=igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )
    stats = {
        row["cfo"]: row
        for row in (
            IgkStatData.objects.exclude(status__in=TERMINATED)
            .filter(HAS_ORDER_Q, igk=igk, contract__isnull=False)
            .values("cfo")
            .annotate(
                all_count=Count("contract", distinct=True),
                all_sum=Sum("plan"),
                all_concluded_count=Count("contract", filter=CONCLUDED_Q, distinct=True),
                all_concluded_sum=Sum("plan", filter=CONCLUDED_Q),
                curr_count=Count("contract", filter=year_q, distinct=True),
                curr_sum=Sum("plan", filter=year_q),
                curr_concluded_count=Count(
                    "contract", filter=CONCLUDED_Q & year_q, distinct=True
                ),
                curr_concluded_sum=Sum("plan", filter=CONCLUDED_Q & year_q),
                curr_not_concluded_count=Count(
                    "contract", filter=NOT_CONCL_Q & year_q, distinct=True
                ),
                curr_not_concluded_sum=Sum("plan", filter=NOT_CONCL_Q & year_q),
                curr_plan=Sum("plan", filter=ADVANCE_Q & year_q),
                curr_fact=Sum("fact", filter=ADVANCE_Q & year_q),
            )
        )
    }
    rows = [cfo_row(cfo, stats.get(cfo, EMPTY_CFO_STATS)) for cfo in available_cfo]
    rows.append(cfo_totals_row(rows))
    return rows
