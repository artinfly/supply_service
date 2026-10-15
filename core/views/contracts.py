"""Страницы по договорам: сводка, КДР, ИГК по годам, реестр, история, дубликаты.

Большинство страниц только отдают HTML-каркас: сами таблицы JavaScript
загружает из JSON API (views/api.py). Исключение — dashboard, где
карточки считаются здесь же через ORM.
"""

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render

from ..models import IgkStatData, NsiIgk
from ..services.dashboards.cards import (
    EMPTY_CFO_STATS,
    cfo_row,
    cfo_totals_row,
    percent,
    to_mln,
)
from ..services.queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    TERMINATED,
    YEARS,
    distinct_cfo,
    valid_year,
)
from .common import base_context, igk_and_cfo_lists

# Позиция договора считается, только если у неё заполнен номер заказа
HAS_ORDER_Q = Q(order__isnull=False) & ~Q(order__regex=r"^\s*$")


# --- КДР и ИГК по годам ---


@login_required
def kdr_table(request, year):
    """Таблица КДР (контрактация по ИГК) за выбранный год."""
    year_int = valid_year(year)
    if str(year_int) != str(year):
        # Неизвестный год в адресе — переводим на ближайший допустимый
        return redirect("kdr_table", year=str(year_int))

    ctx = base_context()
    ctx["year"] = year_int
    return render(request, "kdr_table.html", ctx)


@login_required
def kdr_table_default(request):
    """Перенаправление на КДР за последний год."""
    return redirect("kdr_table", year=str(YEARS[-1]))


# Три таблицы ИГК (заключённые / незаключённые / расторгнутые) устроены
# одинаково и отличаются только типом и заголовком.
_IGK_TABLES = {
    "igk_concluded_table": ("concluded", "Заключённые"),
    "igk_not_concluded_table": ("not_concluded", "Незаключённые"),
    "igk_terminated_table": ("terminated", "Расторгнутые"),
}


def _igk_table(request, year, url_name):
    """Общая страница таблицы ИГК за год (тип берётся из _IGK_TABLES)."""
    year_int = valid_year(year)
    if str(year_int) != str(year):
        return redirect(url_name, year=str(year_int))

    report_type, label = _IGK_TABLES[url_name]
    ctx = base_context()
    ctx.update(
        {
            "year": year_int,
            "report_type": report_type,
            "title": f"ИГК {year_int} — {label}",
            "url_name": url_name,
        }
    )
    return render(request, "igk_table.html", ctx)


@login_required
def igk_concluded_table(request, year):
    """Заключённые договоры по ИГК за год."""
    return _igk_table(request, year, "igk_concluded_table")


@login_required
def igk_concluded_table_default(request):
    return redirect("igk_concluded_table", year=str(YEARS[-1]))


@login_required
def igk_not_concluded_table(request, year):
    """Незаключённые договоры по ИГК за год."""
    return _igk_table(request, year, "igk_not_concluded_table")


@login_required
def igk_not_concluded_table_default(request):
    return redirect("igk_not_concluded_table", year=str(YEARS[-1]))


@login_required
def igk_terminated_table(request, year):
    """Расторгнутые договоры по ИГК за год."""
    return _igk_table(request, year, "igk_terminated_table")


@login_required
def igk_terminated_table_default(request):
    return redirect("igk_terminated_table", year=str(YEARS[-1]))


# --- Реестр всех договоров ---


@login_required
def all_contracts_table(request):
    """Реестр всех договоров с фильтрами (данные — api_all_contracts)."""
    igk_list, cfo_list = igk_and_cfo_lists()
    ctx = base_context()
    ctx.update(
        {
            "igk_list": igk_list,
            "cfo_list": cfo_list,
            # Статусы для чекбоксов «Заключённые / Незаключённые / Расторгнутые»
            "concluded_statuses": list(CONCLUDED),
            "not_concl_statuses": list(NOT_CONCL),
            "terminated_statuses": list(TERMINATED),
        }
    )
    return render(request, "all_contracts.html", ctx)


# --- История изменений (данные — api_history_*) ---


@login_required
def history_status_table(request):
    """Изменения статусов договоров между загрузками."""
    return render(request, "history_status.html", base_context())


@login_required
def history_plan_table(request):
    """Изменения плановых сумм."""
    return render(request, "history_plan.html", base_context())


@login_required
def history_fact_table(request):
    """Изменения фактических сумм."""
    return render(request, "history_fact.html", base_context())


# --- Дубликаты ---


@login_required
def contract_dupes_table(request):
    """Дубликаты позиций договоров (данные — api_contract_dupes*)."""
    with connection.cursor() as cur:
        cur.execute(distinct_cfo())
        cfo_list = [r[0] for r in cur.fetchall()]

    ctx = base_context()
    ctx["cfo_list"] = cfo_list
    return render(request, "contract_dupes.html", ctx)


# --- Сводка «Договорная работа» ---


@login_required
def dashboard(request):
    """Сводка по договорам: карточки (всего и за год) и таблица по ЦФО выбранного ИГК.

    Количество договоров везде — число РАЗНЫХ номеров договоров (distinct),
    суммы — сумма плана по позициям.
    """
    available_igk = NsiIgk.objects.all()
    year = valid_year(request.GET.get("year"))
    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = base_context()
    year_field = f"y{str(year)[-2:]}"

    concluded_q = Q(status__in=CONCLUDED)
    not_concl_q = Q(status__in=NOT_CONCL)
    year_q = Q(**{year_field: True})
    advance_q = Q(payment_type=ADVANCE)

    # Карточки «Всего»: все позиции с заказом, включая расторгнутые
    totals_all = IgkStatData.objects.filter(
        HAS_ORDER_Q, contract__isnull=False
    ).aggregate(
        count=Count("contract", distinct=True),
        plan_sum=Sum("plan"),
        concluded_count=Count("contract", filter=concluded_q, distinct=True),
        concluded_plan=Sum("plan", filter=concluded_q),
        not_concluded_count=Count("contract", filter=not_concl_q, distinct=True),
        not_concluded_plan=Sum("plan", filter=not_concl_q),
    )

    # Карточки «За год»: позиции выбранного года без расторгнутых
    totals_year = (
        IgkStatData.objects.exclude(status__in=TERMINATED)
        .filter(HAS_ORDER_Q, contract__isnull=False, **{year_field: True})
        .aggregate(
            count=Count("contract", distinct=True),
            plan_sum=Sum("plan"),
            concluded_count=Count("contract", filter=concluded_q, distinct=True),
            concluded_plan=Sum("plan", filter=concluded_q),
            advance_plan=Sum("plan", filter=advance_q),
            advance_fact=Sum("fact", filter=advance_q),
        )
    )

    # Таблица по ЦФО выбранного ИГК
    available_cfo = list(
        IgkStatData.objects.filter(igk=selected_igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )

    cfo_stats = {
        row["cfo"]: row
        for row in (
            IgkStatData.objects.exclude(status__in=TERMINATED)
            .filter(HAS_ORDER_Q, igk=selected_igk, contract__isnull=False)
            .values("cfo")
            .annotate(
                all_count=Count("contract", distinct=True),
                all_sum=Sum("plan"),
                all_concluded_count=Count(
                    "contract", filter=concluded_q, distinct=True
                ),
                all_concluded_sum=Sum("plan", filter=concluded_q),
                curr_count=Count("contract", filter=year_q, distinct=True),
                curr_sum=Sum("plan", filter=year_q),
                curr_concluded_count=Count(
                    "contract", filter=concluded_q & year_q, distinct=True
                ),
                curr_concluded_sum=Sum("plan", filter=concluded_q & year_q),
                curr_not_concluded_count=Count(
                    "contract", filter=not_concl_q & year_q, distinct=True
                ),
                curr_not_concluded_sum=Sum("plan", filter=not_concl_q & year_q),
                curr_plan=Sum("plan", filter=advance_q & year_q),
                curr_fact=Sum("fact", filter=advance_q & year_q),
            )
        )
    }

    igk_table = [
        cfo_row(cfo, cfo_stats.get(cfo, EMPTY_CFO_STATS)) for cfo in available_cfo
    ]
    igk_table.append(cfo_totals_row(igk_table))

    year_count = totals_year["count"]
    year_concluded_count = totals_year["concluded_count"]
    year_plan = totals_year["plan_sum"] or 0
    year_concluded_plan = totals_year["concluded_plan"] or 0
    advance_plan = totals_year["advance_plan"] or 0
    advance_fact = totals_year["advance_fact"] or 0

    ctx.update(
        {
            "available_years": YEARS,
            "selected_year": str(year),
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "all_contracts_count": totals_all["count"],
            "all_contracts_sum": to_mln(totals_all["plan_sum"]),
            "all_concluded_count": totals_all["concluded_count"],
            "all_concluded_sum": to_mln(totals_all["concluded_plan"]),
            "all_not_concluded_count": totals_all["not_concluded_count"],
            "all_not_concluded_sum": to_mln(totals_all["not_concluded_plan"]),
            "curr_year_contracts_count": year_count,
            "curr_year_contracts_sum": to_mln(year_plan),
            "curr_year_concluded_count": year_concluded_count,
            "curr_year_concluded_sum": to_mln(year_concluded_plan),
            # «Не заключено за год» = всё за год (без расторгнутых) минус заключённые
            "curr_year_not_concluded_count": year_count - year_concluded_count,
            "curr_year_not_concluded_sum": to_mln(year_plan - year_concluded_plan),
            "curr_year_fact": to_mln(advance_fact),
            "curr_year_plan": to_mln(advance_plan),
            "curr_year_percent_count": percent(year_concluded_count, year_count),
            "curr_year_percent_sum": percent(year_concluded_plan, year_plan),
            "curr_year_percent_prepaid": percent(advance_fact, advance_plan),
            "igk_table": igk_table,
            "has_data": IgkStatData.objects.exists(),
            "no_data_hint": "Договоры ещё не загружены. Нужен файл выгрузки по договорам.",
        }
    )
    return render(request, "dashboard.html", ctx)
