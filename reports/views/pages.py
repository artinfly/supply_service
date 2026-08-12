import os
import tempfile
from io import StringIO

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db import connection
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.expressions import RawSQL
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import IgkStatData, NsiIgk, ZnpData, ZnpDataSAP
from ..services.dashboards import (
    EMPTY_CFO_STATS,
    EMPTY_NOT_ISSUED,
    EMPTY_STAGES,
    EMPTY_ZNP,
    ZNP_STAGE_LABELS,
    ZNP_STAGE_NAMES,
    breakdown_from_stats,
    cfo_breakdown_row,
    cfo_row,
    cfo_totals_row,
    filter_by_year,
    not_issued_aggregates,
    percent,
    sap_cards,
    stage_aggregates,
    to_mln,
    znp_aggregates,
)
from ..services.excel_import import CONTRACT_COLUMNS, ZNP_COLUMNS, ZNP_SAP_COLUMNS
from ..services.queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    SAP_CFO,
    TERMINATED,
    YEARS,
    distinct_agents,
    distinct_cfo,
    distinct_igk_suffixes,
    distinct_sap_cfo,
    distinct_sap_igk,
    needs_znp,
    valid_year,
)
from ..services.sap_status import (
    SAP_STAGE_NAMES,
    SAP_STAGE_PARAMS,
    sap_status_expr,
)


def is_operator(user):
    return user.is_superuser or user.groups.filter(name="operator").exists()


def _ctx(request):
    return {
        "years": YEARS,
        "year_cols": [(y, f"y{str(y)[2:]}") for y in YEARS],
        "is_operator": is_operator(request.user),
    }


HAS_ORDER_Q = Q(order__isnull=False) & ~Q(order__regex=r"^\s*$")


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
    year = valid_year(year)
    ctx = _ctx(request)
    ctx["year"] = year
    return render(request, "kdr_table.html", ctx)


@login_required
def igk_concluded_table(request, year):
    year = valid_year(year)
    ctx = _ctx(request)
    ctx.update(
        {"year": year, "report_type": "concluded", "title": f"ИГК {year} — Заключённые"}
    )
    return render(request, "igk_table.html", ctx)


@login_required
def igk_not_concluded_table(request, year):
    year = valid_year(year)
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
    year = valid_year(year)
    ctx = _ctx(request)
    ctx.update(
        {
            "year": year,
            "report_type": "terminated",
            "title": f"ИГК {year} — Расторгнутые",
        }
    )
    return render(request, "igk_table.html", ctx)


def _igk_and_cfo_lists():
    with connection.cursor() as cur:
        cur.execute(distinct_igk_suffixes())
        igk_list = [r[0] for r in cur.fetchall()]
        cur.execute(distinct_cfo())
        cfo_list = [r[0] for r in cur.fetchall()]
    return igk_list, cfo_list


@login_required
def all_contracts_table(request):
    igk_list, cfo_list = _igk_and_cfo_lists()
    ctx = _ctx(request)
    ctx.update(
        {
            "igk_list": igk_list,
            "cfo_list": cfo_list,
            "concluded_statuses": list(CONCLUDED),
            "not_concl_statuses": list(NOT_CONCL),
            "terminated_statuses": list(TERMINATED),
        }
    )
    return render(request, "all_contracts.html", ctx)


@login_required
def znp_list_table(request):
    igk_list, cfo_list = _igk_and_cfo_lists()
    ctx = _ctx(request)
    ctx.update({"igk_list": igk_list, "cfo_list": cfo_list})
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
    "contracts": "load_contracts",
    "znp": "load_znp",
    "znp_sap": "load_znp_sap",
}
FILE_TYPE_COLUMNS = {
    "contracts": list(CONTRACT_COLUMNS),
    "znp": list(ZNP_COLUMNS),
    "znp_sap": list(ZNP_SAP_COLUMNS),
}
FILE_TYPE_LABELS = {
    "contracts": "Договоры",
    "znp": "ЗНП (ФЗД)",
    "znp_sap": "ЗНП (SAP)",
}


@login_required
def upload_excel(request):
    if not is_operator(request.user):
        return JsonResponse({"error": "нет прав на загрузку файлов"}, status=403)
    result = None
    file_type = request.POST.get("file_type", "contracts")
    if request.method == "POST" and request.FILES.get("excel_file"):
        command = FILE_TYPE_COMMANDS.get(file_type)
        f = request.FILES["excel_file"]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            for chunk in f.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            if command is None:
                raise ValueError(f"Неизвестный тип файла: {file_type}")
            out = StringIO()
            call_command(command, tmp_path, stdout=out)
            result = out.getvalue()
            messages.success(request, "Файл успешно загружен и нормализован")
        except Exception as e:
            text = str(e)
            messages.error(
                request, text if text.startswith("Ошибка") else f"Ошибка: {text}"
            )
            result = str(e)
        finally:
            os.unlink(tmp_path)
    ctx = _ctx(request)
    ctx["result"] = result
    ctx["file_types"] = FILE_TYPE_LABELS
    ctx["file_columns"] = FILE_TYPE_COLUMNS
    ctx["selected_type"] = file_type
    return render(request, "upload.html", ctx)


@login_required
def dashboard(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))

    available_years = YEARS
    available_igk = NsiIgk.objects.all()

    year = valid_year(request.GET.get("year"))

    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = _ctx(request)

    year_field = f"y{str(year)[-2:]}"
    concluded_q = Q(status__in=CONCLUDED)
    not_concl_q = Q(status__in=NOT_CONCL)
    year_q = Q(**{year_field: True})
    advance_q = Q(payment_type=ADVANCE)

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
    totals_year = (
        IgkStatData.objects.exclude(status="Расторгнут")
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

    available_cfo = list(
        IgkStatData.objects.filter(igk=selected_igk)
        .values_list("cfo", flat=True)
        .distinct()
        .order_by("cfo")
    )

    cfo_stats = {
        row["cfo"]: row
        for row in (
            IgkStatData.objects.exclude(status="Расторгнут")
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
            "available_years": available_years,
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
            "curr_year_not_concluded_count": year_count - year_concluded_count,
            "curr_year_not_concluded_sum": to_mln(year_plan - year_concluded_plan),
            "curr_year_fact": to_mln(advance_fact),
            "curr_year_plan": to_mln(advance_plan),
            "curr_year_percent_count": percent(year_concluded_count, year_count),
            "curr_year_percent_sum": percent(year_concluded_plan, year_plan),
            "curr_year_percent_prepaid": percent(advance_fact, advance_plan),
            "igk_table": igk_table,
            "has_data": IgkStatData.objects.exists(),
            "no_data_hint": (
                "Договоры ещё не загружены. Нужен файл выгрузки по договорам."
            ),
        }
    )

    return render(request, "dashboard.html", ctx)


@login_required
def znp_table(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))

    available_years = YEARS
    available_igk = NsiIgk.objects.all()

    year = valid_year(request.GET.get("year"))

    selected_igk = request.GET.get("igk", "") or str(available_igk.first() or "")

    ctx = _ctx(request)

    has_znp = Exists(ZnpData.objects.filter(parent=OuterRef("pk")))

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

    def _znp_qs(igk=None):
        qs = ZnpData.objects.filter(parent__status__in=CONCLUDED)
        if igk is not None:
            qs = qs.filter(parent__igk=igk)
        return qs

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


@login_required
def znp_sap_table(request):
    if not request.user.is_superuser:
        return render(request, "access_denied.html", _ctx(request))

    ctx = _ctx(request)
    qs = ZnpDataSAP.objects.annotate(sap_status=sap_status_expr).filter(cfo__in=SAP_CFO)

    def _breakdown(qs):
        return sap_cards(
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
        cfo_breakdown_row(
            cfo,
            sap_cards(cfo_totals.get(cfo), cfo_status.get(cfo, {})),
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
            "cfo_table": cfo_table,
            "cfo_total_row": cfo_total_row,
            "has_data": all_breakdown["total_count"] > 0,
            "no_data_hint": (
                "Заявки на платёж из SAP ещё не загружены. "
                "Нужен файл выгрузки ЗНП (SAP)."
            ),
        }
    )
    return render(request, "znp_sap_table.html", ctx)


@login_required
def znp_sap_list_table(request):
    with connection.cursor() as cur:
        cur.execute(distinct_sap_igk())
        igk_list = [r[0] for r in cur.fetchall()]
        cur.execute(distinct_sap_cfo())
        cfo_list = [r[0] for r in cur.fetchall()]
    ctx = _ctx(request)
    ctx.update({"igk_list": igk_list, "cfo_list": cfo_list})
    return render(request, "znp_sap_list.html", ctx)
