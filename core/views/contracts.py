"""Страницы по договорам: сводка, КДР, ИГК по годам, реестр, история, дубликаты.

Большинство страниц только отдают HTML-каркас: сами таблицы JavaScript
загружает из JSON API (views/api.py). Карточки сводки считает
services/dashboards/contracts.py.
"""

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.shortcuts import redirect, render

from ..models import IgkStatData, NsiIgk
from ..services.dashboards import contracts as contract_cards
from ..services.queries import (
    CONCLUDED,
    NOT_CONCL,
    TERMINATED,
    YEARS,
    distinct_cfo,
    valid_year,
)
from .common import base_context, igk_and_cfo_lists


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
    """Сводка по договорам: карточки (всего и за год) и таблица по ЦФО выбранного ИГК."""
    available_igk = NsiIgk.objects.all()
    year = valid_year(request.GET.get("year"))
    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = base_context()
    ctx.update(
        {
            "available_years": YEARS,
            "selected_year": str(year),
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            **contract_cards.total_cards(),
            **contract_cards.year_cards(year),
            "igk_table": contract_cards.cfo_table(selected_igk, year),
            "has_data": IgkStatData.objects.exists(),
            "no_data_hint": "Договоры ещё не загружены. Нужен файл выгрузки по договорам.",
        }
    )
    return render(request, "dashboard.html", ctx)
