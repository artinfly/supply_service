"""Раздел «Краткая справка»: страница загрузки и формирование ZIP со справками."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from ..services.reports.sum_report import generate_sum_reports_response
from .common import base_context

logger = logging.getLogger(__name__)


@login_required
def sum_report_page(request):
    """Страница загрузки файла «Свод отчёт по ИГК»."""
    return render(request, "sum_report.html", base_context())


@login_required
def sum_report_upload(request):
    """Принимает файл (AJAX) и возвращает ZIP со справками по каждому листу-ИГК.

    При ошибке отвечает JSON {"error": ...} — страница показывает его под формой.
    """
    if request.method != "POST" or not request.FILES.get("excel_file"):
        return JsonResponse({"error": "Файл не прикреплён"}, status=400)

    file = request.FILES["excel_file"]
    is_cycle = request.POST.get("report_type") == "cycle"

    try:
        return generate_sum_reports_response(
            file, is_cycle=is_cycle, username=request.user.username
        )
    except Exception as e:
        logger.exception("Ошибка формирования краткой справки из %s", file.name)
        return JsonResponse({"error": str(e)}, status=400)
