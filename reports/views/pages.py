import os
import tempfile

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.management import call_command
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render, redirect
from io import StringIO

from ..services.queries import (
    CONCLUDED, NOT_CONCL, TERMINATED,
    YEARS, YEAR_COL, distinct_igk_suffixes, distinct_agents,
)


def is_operator(user):
    return user.is_superuser or user.groups.filter(name='operator').exists()


def _ctx(request):
    return {
        'years': YEARS,
        'year_cols': [(y, f'y{str(y)[2:]}') for y in YEARS],
        'is_operator': is_operator(request.user),
    }


def login_view(request):
    if request.user.is_authenticated:
        return redirect('/reports/')
    error = False
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        if user:
            login(request, user)
            return redirect('/reports/')
        error = True
    return render(request, 'reports/login.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def index(request):
    return render(request, 'reports/index.html', _ctx(request))


@login_required
def kdr_table(request, year):
    ctx = _ctx(request)
    ctx['year'] = year
    return render(request, 'reports/kdr_table.html', ctx)


@login_required
def igk_concluded_table(request, year):
    ctx = _ctx(request)
    ctx.update({'year': year, 'report_type': 'concluded', 'title': f'ИГК {year} — Заключённые'})
    return render(request, 'reports/igk_table.html', ctx)


@login_required
def igk_not_concluded_table(request, year):
    ctx = _ctx(request)
    ctx.update({'year': year, 'report_type': 'not_concluded', 'title': f'ИГК {year} — Незаключённые'})
    return render(request, 'reports/igk_table.html', ctx)


@login_required
def igk_terminated_table(request, year):
    ctx = _ctx(request)
    ctx.update({'year': year, 'report_type': 'terminated', 'title': f'ИГК {year} — Расторгнутые'})
    return render(request, 'reports/igk_table.html', ctx)


@login_required
def all_contracts_table(request):
    with connection.cursor() as cur:
        cur.execute(distinct_igk_suffixes())
        igk_list = [r[0] for r in cur.fetchall()]
    ctx = _ctx(request)
    ctx.update({
        'igk_list': igk_list,
        'concluded_statuses': list(CONCLUDED),
        'not_concl_statuses': list(NOT_CONCL),
        'terminated_statuses': list(TERMINATED),
    })
    return render(request, 'reports/all_contracts.html', ctx)


@login_required
def history_status_table(request):
    return render(request, 'reports/history_status.html', _ctx(request))


@login_required
def history_plan_table(request):
    return render(request, 'reports/history_plan.html', _ctx(request))


@login_required
def history_fact_table(request):
    return render(request, 'reports/history_fact.html', _ctx(request))


@login_required
def contract_dupes_table(request):
    return render(request, 'reports/contract_dupes.html', _ctx(request))


@login_required
def export_page(request):
    with connection.cursor() as cur:
        cur.execute(distinct_agents())
        agents = [r[0] for r in cur.fetchall()]
    ctx = _ctx(request)
    ctx['agents'] = agents
    return render(request, 'reports/export.html', ctx)


@login_required
def upload_excel(request):
    if not is_operator(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)
    result = None
    if request.method == 'POST' and request.FILES.get('excel_file'):
        f = request.FILES['excel_file']
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            for chunk in f.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            out = StringIO()
            call_command('import_excel', tmp_path, stdout=out)
            call_command('normalize_staging', stdout=out)
            result = out.getvalue()
            messages.success(request, 'Файл успешно загружен и нормализован')
        except Exception as e:
            messages.error(request, f'Ошибка: {e}')
            result = str(e)
        finally:
            os.unlink(tmp_path)
    ctx = _ctx(request)
    ctx['result'] = result
    return render(request, 'reports/upload.html', ctx)