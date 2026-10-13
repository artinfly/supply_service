"""Представления для модуля суммарных отчётов."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from ..services.sum_report import generate_sum_reports_response


@login_required
def sum_report_page(request):
    """Отображает страницу загрузки файла для суммарного отчёта."""
    return render(request, "sum_report.html")


@login_required
def sum_report_upload(request):
    """Обрабатывает загрузку Excel-файла и генерирует суммарный отчёт."""
    if request.method != "POST" or not request.FILES.get("excel_file"):
        return JsonResponse({"error": "Файл не прикреплён"}, status=400)

    file = request.FILES["excel_file"]
    is_cycle = request.POST.get("report_type") == "cycle"

    # @login_required гарантирует, что пользователь аутентифицирован
    username = request.user.username

    try:
        return generate_sum_reports_response(file, is_cycle=is_cycle, username=username)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
