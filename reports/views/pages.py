import os
import tempfile
from datetime import date as _date
from io import StringIO

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db import connection
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import IgkStatData, NsiIgk, ZnpData, ZnpDataSAP
from ..services.queries import (
    CONCLUDED,
    NOT_CONCL,
    TERMINATED,
    YEARS,
    distinct_agents,
    distinct_igk_suffixes,
)
from ..services.sap_status import sap_status_expr


def is_operator(user):
    return user.is_superuser or user.groups.filter(name="operator").exists()


def _ctx(request):
    return {
        "years": YEARS,
        "year_cols": [(y, f"y{str(y)[2:]}") for y in YEARS],
        "is_operator": is_operator(request.user),
    }


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/reports/")
    error = False
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
        if user:
            login(request, user)
            return redirect("/reports/")
        error = True
    return render(request, "login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def index(request):
    return render(request, "index.html", _ctx(request))


@login_required
def kdr_table(request, year):
    ctx = _ctx(request)
    ctx["year"] = year
    return render(request, "kdr_table.html", ctx)


@login_required
def igk_concluded_table(request, year):
    ctx = _ctx(request)
    ctx.update(
        {"year": year, "report_type": "concluded", "title": f"ИГК {year} — Заключённые"}
    )
    return render(request, "igk_table.html", ctx)


@login_required
def igk_not_concluded_table(request, year):
    ctx = _ctx(request)
    ctx.update(
        {
            "year": year,
            "report_type": "not_concluded",
            "title": f"ИГК {year} — Незаключённые",
        }
    )
    return render(request, "igk_table.html", ctx)


@login_required
def igk_terminated_table(request, year):
    ctx = _ctx(request)
    ctx.update(
        {
            "year": year,
            "report_type": "terminated",
            "title": f"ИГК {year} — Расторгнутые",
        }
    )
    return render(request, "igk_table.html", ctx)


@login_required
def all_contracts_table(request):
    with connection.cursor() as cur:
        cur.execute(distinct_igk_suffixes())
        igk_list = [r[0] for r in cur.fetchall()]
    ctx = _ctx(request)
    ctx.update(
        {
            "igk_list": igk_list,
            "concluded_statuses": list(CONCLUDED),
            "not_concl_statuses": list(NOT_CONCL),
            "terminated_statuses": list(TERMINATED),
        }
    )
    return render(request, "all_contracts.html", ctx)


@login_required
def znp_list_table(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))
    with connection.cursor() as cur:
        cur.execute(distinct_igk_suffixes())
        igk_list = [r[0] for r in cur.fetchall()]
    ctx = _ctx(request)
    ctx["igk_list"] = igk_list
    return render(request, "znp_list.html", ctx)


@login_required
def history_status_table(request):
    return render(request, "history_status.html", _ctx(request))


@login_required
def history_plan_table(request):
    return render(request, "history_plan.html", _ctx(request))


@login_required
def history_fact_table(request):
    return render(request, "history_fact.html", _ctx(request))


@login_required
def contract_dupes_table(request):
    return render(request, "contract_dupes.html", _ctx(request))


@login_required
def export_page(request):
    with connection.cursor() as cur:
        cur.execute(distinct_agents())
        agents = [r[0] for r in cur.fetchall()]
    ctx = _ctx(request)
    ctx["agents"] = agents
    return render(request, "export.html", ctx)


FILE_TYPE_COMMANDS = {
    "contracts": ("import_excel", "normalize_staging"),
    "znp": ("import_znp_excel", "normalize_znp_staging"),
    "znp_sap": ("import_znp_sap_excel", "normalize_znp_sap_staging"),
}
FILE_TYPE_LABELS = {
    "contracts": "Договоры",
    "znp": "ЗНП (ФЗД)",
    "znp_sap": "ЗНП (SAP)",
}


@login_required
def upload_excel(request):
    if not is_operator(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    result = None
    if request.method == "POST" and request.FILES.get("excel_file"):
        file_type = request.POST.get("file_type", "contracts")
        commands = FILE_TYPE_COMMANDS.get(file_type)
        f = request.FILES["excel_file"]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            for chunk in f.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            if commands is None:
                raise ValueError(f"Неизвестный тип файла: {file_type}")
            import_command, normalize_command = commands
            out = StringIO()
            call_command(import_command, tmp_path, stdout=out)
            call_command(normalize_command, stdout=out)
            result = out.getvalue()
            messages.success(request, "Файл успешно загружен и нормализован")
        except Exception as e:
            messages.error(request, f"Ошибка: {e}")
            result = str(e)
        finally:
            os.unlink(tmp_path)
    ctx = _ctx(request)
    ctx["result"] = result
    ctx["file_types"] = FILE_TYPE_LABELS
    return render(request, "upload.html", ctx)


def _resolve_year(request):
    # мусор в ?year= и год без y-поля на модели не должны ронять страницу
    try:
        year = int(request.GET.get("year", ""))
    except (TypeError, ValueError):
        year = _date.today().year
    if year not in YEARS:
        year = YEARS[-1]
    return year


def _filter_by_year(queryset, year, field_prefix=""):
    # field_prefix — для фильтра через связанную модель, например "parent__"
    field_name = f"{field_prefix}y{str(year)[-2:]}"
    return queryset.filter(**{field_name: True})


@login_required
def dashboard(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))

    available_years = YEARS
    available_igk = NsiIgk.objects.all()

    year = _resolve_year(request)

    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = _ctx(request)

    all_contracts_stats = (
        IgkStatData.objects.filter(
            contract__isnull=False,
        )
        .exclude(order="")
        .values("contract")
        .annotate(
            count=Count("pp_id"),
            contract_sum=Sum("plan"),
        )
    )

    all_concluded_stats = (
        IgkStatData.objects.filter(
            contract__isnull=False,
            status__in=CONCLUDED,
        )
        .exclude(order="")
        .values("contract")
        .annotate(
            count=Count("pp_id"),
            contract_sum=Sum("plan"),
        )
    )

    all_not_concluded_stats = (
        IgkStatData.objects.filter(
            contract__isnull=False,
            status__in=NOT_CONCL,
        )
        .exclude(order="")
        .values("contract")
        .annotate(
            count=Count("pp_id"),
            contract_sum=Sum("plan"),
        )
    )

    curr_year_contracts_stats = (
        IgkStatData.objects.exclude(
            status="Расторгнут",
        )
        .filter(contract__isnull=False, order__isnull=False)
        .values("contract")
        .annotate(
            count=Count("pp_id"),
            contract_sum=Sum("plan"),
        )
    )

    curr_year_concluded_stats = (
        IgkStatData.objects.exclude(
            status="Расторгнут",
        )
        .filter(
            contract__isnull=False,
            order__isnull=False,
            status__in=CONCLUDED,
        )
        .values("contract")
        .annotate(
            count=Count("pp_id"),
            contract_sum=Sum("plan"),
        )
    )

    curr_year_sums = (
        IgkStatData.objects.exclude(
            status="Расторгнут",
        )
        .filter(
            contract__isnull=False,
            order__isnull=False,
            payment_type="Аванс",
        )
        .values("contract")
        .annotate(
            count=Count("pp_id"),
            plan=Sum("plan"),
            fact=Sum("fact"),
        )
    )

    available_cfo = list(
        IgkStatData.objects.filter(igk=selected_igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )

    # один запрос с группировкой по cfo вместо запроса на каждый ЦФО
    year_field = f"y{str(year)[-2:]}"
    concluded_q = Q(status__in=CONCLUDED)
    not_concl_q = Q(status__in=NOT_CONCL)
    year_q = Q(**{year_field: True})
    advance_q = Q(payment_type="Аванс")

    cfo_stats = {
        row["cfo"]: row
        for row in (
            IgkStatData.objects.exclude(status="Расторгнут")
            .filter(igk=selected_igk, contract__isnull=False, order__isnull=False)
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
    _empty_cfo_stats = {
        "all_count": 0,
        "all_sum": None,
        "all_concluded_count": 0,
        "all_concluded_sum": None,
        "curr_count": 0,
        "curr_sum": None,
        "curr_concluded_count": 0,
        "curr_concluded_sum": None,
        "curr_not_concluded_count": 0,
        "curr_not_concluded_sum": None,
        "curr_plan": None,
        "curr_fact": None,
    }

    igk_table = []

    for ac in available_cfo:
        s = cfo_stats.get(ac, _empty_cfo_stats)
        all_sum = s["all_sum"] or 0
        all_concluded_sum = s["all_concluded_sum"] or 0
        curr_sum = s["curr_sum"] or 0
        curr_concluded_sum = s["curr_concluded_sum"] or 0
        curr_not_concluded_sum = s["curr_not_concluded_sum"] or 0
        curr_year_plan_cfo = s["curr_plan"] or 0
        curr_year_fact_cfo = s["curr_fact"] or 0
        concluded_percent_sum = curr_concluded_sum / curr_sum if curr_sum != 0 else 0

        igk_table.append(
            {
                ac: (
                    s["all_count"],
                    all_sum / 1000000,
                    s["all_concluded_count"],
                    all_concluded_sum / 1000000,
                    s["curr_count"],
                    curr_sum / 1000000,
                    s["curr_concluded_count"],
                    (
                        (s["curr_concluded_count"] / s["curr_count"]) * 100
                        if s["curr_count"] != 0
                        else 0
                    ),
                    curr_concluded_sum / 1000000,
                    concluded_percent_sum * 100,
                    s["curr_not_concluded_count"],
                    curr_not_concluded_sum / 1000000,
                    curr_year_plan_cfo / 1000000,
                    curr_year_fact_cfo / 1000000,
                    (
                        (curr_year_fact_cfo / curr_year_plan_cfo) * 100
                        if curr_year_plan_cfo != 0
                        else 0
                    ),
                )
            }
        )

    summed_indices = [0, 1, 2, 3, 4, 5, 6, 8, 10, 11, 12, 13]
    totals = {i: 0 for i in summed_indices}
    for row in igk_table:
        values = next(iter(row.values()))
        for i in summed_indices:
            totals[i] += values[i]

    contracts_count = totals[0]
    contracts_sum = totals[1]
    concluded_contracts_count = totals[2]
    concluded_contracts_sum = totals[3]
    curr_year_contracts = totals[4]
    curr_year_contracts_sum_cfo = totals[5]
    curr_year_concluded_contracts = totals[6]
    curr_year_concluded_contracts_sum = totals[8]
    curr_year_not_concluded_contracts = totals[10]
    curr_year_not_concluded_contracts_sum = totals[11]
    curr_year_plan_cfo_summary = totals[12]
    curr_year_fact_cfo_summary = totals[13]

    igk_table.append(
        {
            "ИТОГО": (
                contracts_count,
                contracts_sum,
                concluded_contracts_count,
                concluded_contracts_sum,
                curr_year_contracts,
                curr_year_contracts_sum_cfo,
                curr_year_concluded_contracts,
                (
                    (curr_year_concluded_contracts / curr_year_contracts) * 100
                    if curr_year_contracts != 0
                    else 0
                ),
                curr_year_concluded_contracts_sum,
                (
                    (curr_year_concluded_contracts_sum / curr_year_contracts_sum_cfo)
                    * 100
                    if curr_year_contracts_sum_cfo != 0
                    else 0
                ),
                curr_year_not_concluded_contracts,
                curr_year_not_concluded_contracts_sum,
                curr_year_plan_cfo_summary,
                curr_year_fact_cfo_summary,
                (
                    (curr_year_fact_cfo_summary / curr_year_plan_cfo_summary) * 100
                    if curr_year_plan_cfo_summary != 0
                    else 0
                ),
            )
        }
    )

    curr_year_contracts_stats = _filter_by_year(curr_year_contracts_stats, year)
    curr_year_concluded_stats = _filter_by_year(curr_year_concluded_stats, year)
    curr_year_sums = _filter_by_year(curr_year_sums, year)

    all_contracts_sum = sum(item["contract_sum"] or 0 for item in all_contracts_stats)
    all_concluded_sum = sum(item["contract_sum"] or 0 for item in all_concluded_stats)
    all_not_concluded_sum = sum(
        item["contract_sum"] or 0 for item in all_not_concluded_stats
    )
    curr_year_contracts_sum = sum(
        item["contract_sum"] or 0 for item in curr_year_contracts_stats
    )
    curr_year_concluded_sum = sum(
        item["contract_sum"] or 0 for item in curr_year_concluded_stats
    )
    curr_year_fact = sum(item["fact"] or 0 for item in curr_year_sums)
    curr_year_plan = sum(item["plan"] or 0 for item in curr_year_sums)

    curr_year_contracts_count = curr_year_contracts_stats.count()
    curr_year_concluded_count = curr_year_concluded_stats.count()

    ctx.update(
        {
            "available_years": available_years,
            "selected_year": str(year),
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "all_contracts_count": all_contracts_stats.count(),
            "all_contracts_sum": all_contracts_sum / 1000000,
            "all_concluded_count": all_concluded_stats.count(),
            "all_concluded_sum": all_concluded_sum / 1000000,
            "all_not_concluded_count": all_not_concluded_stats.count(),
            "all_not_concluded_sum": all_not_concluded_sum / 1000000,
            "curr_year_contracts_count": curr_year_contracts_count,
            "curr_year_contracts_sum": curr_year_contracts_sum / 1000000,
            "curr_year_concluded_count": curr_year_concluded_count,
            "curr_year_concluded_sum": curr_year_concluded_sum / 1000000,
            "curr_year_not_concluded_count": curr_year_contracts_count
            - curr_year_concluded_count,
            "curr_year_not_concluded_sum": (
                curr_year_contracts_sum - curr_year_concluded_sum
            )
            / 1000000,
            "curr_year_fact": curr_year_fact / 1000000,
            "curr_year_plan": curr_year_plan / 1000000,
            "curr_year_percent_count": (
                (curr_year_concluded_count / curr_year_contracts_count) * 100
                if curr_year_contracts_count != 0
                else 0
            ),
            "curr_year_percent_sum": (
                (curr_year_concluded_sum / curr_year_contracts_sum) * 100
                if curr_year_contracts_sum != 0
                else 0
            ),
            "curr_year_percent_prepaid": (
                (curr_year_fact / curr_year_plan) * 100 if curr_year_plan != 0 else 0
            ),
            "igk_table": igk_table,
            "has_data": IgkStatData.objects.exists(),
            "no_data_hint": (
                "Договоры ещё не загружены. Нужен файл выгрузки по договорам."
            ),
        }
    )

    return render(request, "dashboard.html", ctx)


ZNP_STAGE_LABELS = {
    "not_issued": "Не оформлено ЗнП",
    "advance": "Оформлено ЗнП (Аванс)",
    "advance_paid": "Оплачено ЗнП (Аванс)",
    "postpayment": "Оформлено ЗнП (Постоплата)",
    "postpayment_paid": "Оплачено ЗнП (Постоплата)",
}
ZNP_STAGE_NAMES = list(ZNP_STAGE_LABELS.values())

_EMPTY_NOT_ISSUED = {"count": 0, "plan_sum": None}
_EMPTY_ZNP = {
    "issued_count": 0,
    "issued_sum": None,
    "advance_count": 0,
    "advance_sum": None,
    "advance_paid_count": 0,
    "advance_paid_sum": None,
    "postpayment_count": 0,
    "postpayment_sum": None,
    "postpayment_paid_count": 0,
    "postpayment_paid_sum": None,
}


def _breakdown_from_stats(ni, zs):
    """Собирает карточки этапов ЗНП из уже посчитанных чисел.

    Единственное место, где живёт эта арифметика: и сводка по всем ЗНП, и строки
    по ЦФО приходят сюда с одинаковым набором полей. Раньше расчёт был написан
    дважды и успел разойтись.
    """
    to_mln = lambda v: (v or 0) / 1000000  # noqa: E731

    not_issued_count = ni["count"] or 0
    not_issued_sum = to_mln(ni["plan_sum"])

    issued_count = zs["issued_count"] or 0
    issued_sum = to_mln(zs["issued_sum"])
    advance_count = zs["advance_count"] or 0
    advance_paid_count = zs["advance_paid_count"] or 0
    postpayment_count = zs["postpayment_count"] or 0
    postpayment_paid_count = zs["postpayment_paid_count"] or 0

    total = not_issued_count + issued_count

    def _pct(part, whole):
        return (part / whole * 100) if whole else 0

    def _card(count, plan_sum, status_param, percent=None):
        return {
            "count": count,
            "sum": plan_sum,
            "percent": _pct(count, total) if percent is None else percent,
            "status_param": status_param,
        }

    return {
        "total_count": total,
        "total_sum": not_issued_sum + issued_sum,
        "not_issued": _card(not_issued_count, not_issued_sum, "not_issued"),
        "issued": _card(issued_count, issued_sum, "advance,postpayment"),
        "advance": _card(
            advance_count,
            to_mln(zs["advance_sum"]),
            "advance",
            percent=_pct(advance_count, issued_count),
        ),
        "advance_paid": _card(
            advance_paid_count,
            to_mln(zs["advance_paid_sum"]),
            "advance_paid",
            percent=_pct(advance_paid_count, advance_count),
        ),
        "postpayment": _card(
            postpayment_count,
            to_mln(zs["postpayment_sum"]),
            "postpayment",
            percent=_pct(postpayment_count, issued_count),
        ),
        "postpayment_paid": _card(
            postpayment_paid_count,
            to_mln(zs["postpayment_paid_sum"]),
            "postpayment_paid",
            percent=_pct(postpayment_paid_count, postpayment_count),
        ),
    }


@login_required
def znp_table(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))

    available_years = YEARS
    available_igk = NsiIgk.objects.all()

    year = _resolve_year(request)

    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = _ctx(request)

    has_znp = Exists(ZnpData.objects.filter(parent=OuterRef("pk")))

    def _not_issued_qs(igk=None):
        qs = (
            IgkStatData.objects.filter(status__in=CONCLUDED)
            .annotate(has_znp=has_znp)
            .filter(has_znp=False)
        )
        if igk is not None:
            qs = qs.filter(igk=igk)
        return qs

    def _znp_qs(igk=None):
        qs = ZnpData.objects.filter(parent__status__in=CONCLUDED)
        if igk is not None:
            qs = qs.filter(parent__igk=igk)
        return qs

    all_not_issued_qs = _not_issued_qs()
    all_znp_qs = _znp_qs()
    year_not_issued_qs = _filter_by_year(all_not_issued_qs, year)
    year_znp_qs = _filter_by_year(all_znp_qs, year, field_prefix="parent__")

    def _breakdown(not_issued_qs, znp_qs):
        not_issued_agg = not_issued_qs.aggregate(
            count=Count("pp_id"), plan_sum=Sum("plan")
        )
        advance_q = Q(parent__payment_type="Аванс")
        postpayment_q = Q(parent__payment_type="Постоплата")
        paid_q = Q(fact_sum__isnull=False)
        znp_agg = znp_qs.aggregate(
            issued_count=Count("id"),
            issued_sum=Sum("plan_sum"),
            advance_count=Count("id", filter=advance_q),
            advance_sum=Sum("plan_sum", filter=advance_q),
            advance_paid_count=Count("id", filter=advance_q & paid_q),
            advance_paid_sum=Sum("fact_sum", filter=advance_q & paid_q),
            postpayment_count=Count("id", filter=postpayment_q),
            postpayment_sum=Sum("plan_sum", filter=postpayment_q),
            postpayment_paid_count=Count("id", filter=postpayment_q & paid_q),
            postpayment_paid_sum=Sum("fact_sum", filter=postpayment_q & paid_q),
        )
        return _breakdown_from_stats(not_issued_agg, znp_agg)

    all_breakdown = _breakdown(all_not_issued_qs, all_znp_qs)
    year_breakdown = _breakdown(year_not_issued_qs, year_znp_qs)

    available_cfo = list(
        IgkStatData.objects.filter(igk=selected_igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )

    igk_not_issued_qs = _filter_by_year(_not_issued_qs(igk=selected_igk), year)
    igk_znp_qs = _filter_by_year(
        _znp_qs(igk=selected_igk), year, field_prefix="parent__"
    )

    def _row_from_breakdown(label, breakdown):
        return {
            "cfo": label,
            "total_count": breakdown["total_count"],
            "total_sum": breakdown["total_sum"],
            "cells": [
                {
                    "status_param": status,
                    "count": breakdown[status]["count"],
                    "sum": breakdown[status]["sum"],
                }
                for status in ZNP_STAGE_LABELS
            ],
        }

    # два запроса с группировкой по cfo вместо шести на каждый ЦФО
    not_issued_stats = {
        row["cfo"]: row
        for row in igk_not_issued_qs.values("cfo").annotate(
            count=Count("pp_id"), plan_sum=Sum("plan")
        )
    }

    advance_q = Q(parent__payment_type="Аванс")
    postpayment_q = Q(parent__payment_type="Постоплата")
    paid_q = Q(fact_sum__isnull=False)
    znp_stats = {
        row["parent__cfo"]: row
        for row in igk_znp_qs.values("parent__cfo").annotate(
            issued_count=Count("id"),
            issued_sum=Sum("plan_sum"),
            advance_count=Count("id", filter=advance_q),
            advance_sum=Sum("plan_sum", filter=advance_q),
            advance_paid_count=Count("id", filter=advance_q & paid_q),
            advance_paid_sum=Sum("fact_sum", filter=advance_q & paid_q),
            postpayment_count=Count("id", filter=postpayment_q),
            postpayment_sum=Sum("plan_sum", filter=postpayment_q),
            postpayment_paid_count=Count("id", filter=postpayment_q & paid_q),
            postpayment_paid_sum=Sum("fact_sum", filter=postpayment_q & paid_q),
        )
    }

    cfo_table = [
        _row_from_breakdown(
            cfo,
            _breakdown_from_stats(
                not_issued_stats.get(cfo, _EMPTY_NOT_ISSUED),
                znp_stats.get(cfo, _EMPTY_ZNP),
            ),
        )
        for cfo in available_cfo
    ]
    cfo_total_row = _row_from_breakdown(
        "ИТОГО", _breakdown(igk_not_issued_qs, igk_znp_qs)
    )

    ctx.update(
        {
            "available_years": available_years,
            "selected_year": str(year),
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "stage_names": ZNP_STAGE_NAMES,
            "all": all_breakdown,
            "year": year_breakdown,
            "cfo_table": cfo_table,
            "cfo_total_row": cfo_total_row,
            "has_data": all_breakdown["total_count"] > 0,
            "no_data_hint": (
                "Нет ни договоров, ни заявок на платёж (ФЗД). "
                "Нужны файлы выгрузки по договорам и по ЗНП."
            ),
        }
    )
    return render(request, "znp_table.html", ctx)


SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
}
SAP_STAGE_NAMES = list(SAP_STAGE_LABELS.values())
SAP_STAGE_PARAMS = list(SAP_STAGE_LABELS.keys())


def _sap_cards(total_row, status_rows):
    """Карточки этапов SAP из готовых чисел — единственное место расчёта.

    Сюда одинаково приходят и сводка по всем заявкам, и строка одного ЦФО.
    """
    total = (total_row or {}).get("total") or 0
    total_sum = ((total_row or {}).get("total_sum") or 0) / 1000000

    def _card(status):
        row = status_rows.get(status)
        count = (row or {}).get("count") or 0
        vv_sum = ((row or {}).get("vv_sum") or 0) / 1000000
        return {
            "count": count,
            "sum": vv_sum,
            "percent": (count / total * 100) if total else 0,
            "status_param": status,
        }

    return {
        "total_count": total,
        "total_sum": total_sum,
        **{status: _card(status) for status in SAP_STAGE_PARAMS},
    }


@login_required
def znp_sap_table(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))

    ctx = _ctx(request)
    allowed_cfo = [str(n) for n in range(420, 430)]
    qs = ZnpDataSAP.objects.annotate(sap_status=sap_status_expr).filter(
        cfo__in=allowed_cfo
    )

    def _breakdown(qs):
        return _sap_cards(
            qs.aggregate(total=Count("id"), total_sum=Sum("vv_sum")),
            {
                row["sap_status"]: row
                for row in qs.values("sap_status").annotate(
                    count=Count("id"), vv_sum=Sum("vv_sum")
                )
            },
        )

    all_breakdown = _breakdown(qs)
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

    def _row_from_breakdown(label, breakdown):
        return {
            "cfo": label,
            "total_count": breakdown["total_count"],
            "total_sum": breakdown["total_sum"],
            "cells": [
                {
                    "status_param": status,
                    "count": breakdown[status]["count"],
                    "sum": breakdown[status]["sum"],
                }
                for status in SAP_STAGE_PARAMS
            ],
        }

    # два запроса с группировкой вместо пары на каждый ЦФО
    cfo_totals = {
        row["cfo"]: row
        for row in cfo_qs.values("cfo").annotate(
            total=Count("id"), total_sum=Sum("vv_sum")
        )
    }
    cfo_status = {}
    for row in cfo_qs.values("cfo", "sap_status").annotate(
        count=Count("id"), vv_sum=Sum("vv_sum")
    ):
        cfo_status.setdefault(row["cfo"], {})[row["sap_status"]] = row

    cfo_table = [
        _row_from_breakdown(
            cfo, _sap_cards(cfo_totals.get(cfo), cfo_status.get(cfo, {}))
        )
        for cfo in available_cfo
    ]
    cfo_total_row = _row_from_breakdown("ИТОГО", _breakdown(cfo_qs))

    ctx.update(
        {
            "stage_names": SAP_STAGE_NAMES,
            "available_igk": available_igk,
            "selected_igk": selected_igk,
            "all": all_breakdown,
            "cfo_table": cfo_table,
            "cfo_total_row": cfo_total_row,
            "has_data": all_breakdown["total_count"] > 0,
            # у страницы нет общего переключателя года — он нужен только графику
            "current_year": str(_resolve_year(request)),
            "no_data_hint": (
                "Заявки на платёж из SAP ещё не загружены. "
                "Нужен файл выгрузки ЗНП (SAP)."
            ),
        }
    )
    return render(request, "znp_sap_table.html", ctx)


@login_required
def znp_sap_list_table(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))
    return render(request, "znp_sap_list.html", _ctx(request))
