"""Общее для тестов: пользователи с правами и Excel-файлы для загрузки."""

import io

import openpyxl
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.services.importing.excel_import import CONTRACT_COLUMNS, ZNP_COLUMNS


def make_user(username="user", *perms, superuser=False):
    """Пользователь с правами разделов (например, "access_dashboard")."""
    if superuser:
        return User.objects.create_superuser(username, password="pass")
    user = User.objects.create_user(username, password="pass")
    for codename in perms:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return user


def xlsx_bytes(rows, sheet_title=None):
    """Содержимое .xlsx с одним листом из списка строк."""
    wb = openpyxl.Workbook()
    ws = wb.active
    if sheet_title:
        ws.title = sheet_title
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def contract_row(
    igk="000000001111",
    agent="ООО Ромашка",
    cfo="421",
    contract="Д-1/25",
    status="Подписан",
    payment="Аванс",
    item="Подшипники",
    order="1001",
    plan=1000,
    fact=400,
    remainder=600,
    tolerance=0,
    stage="Этап 1",
    plan_date="15.03.2026",
    contract_sum=5000,
    year="2026",
):
    """Строка файла договоров в порядке колонок CONTRACT_COLUMNS."""
    return [igk, agent, cfo, contract, status, payment, item, order, plan, fact,
            remainder, tolerance, stage, plan_date, contract_sum, year]  # fmt: skip


def contracts_file(*rows):
    """Файл выгрузки договоров: строка-заголовок отчёта, шапка и строки."""
    return xlsx_bytes([["Выгрузка договоров"], list(CONTRACT_COLUMNS), *rows])


def znp_row(
    plan_doc="ПД-1", status="Утвержден", plan_sum=300, fact_sum=None, **contract
):
    """Строка файла заявок ФЗД, привязанная к позиции договора contract_row(**contract)."""
    c = contract_row(**contract)
    return [c[0], c[0], c[1], plan_doc, c[12], "Оплата аванса", c[3], "20.03.2026",
            "", plan_sum, fact_sum, "Аванс", status, "01.03.2026"]  # fmt: skip


def znp_file(*rows):
    return xlsx_bytes([list(ZNP_COLUMNS), *rows])


def upload(client, file_type, content, name="file.xlsx"):
    """POST на страницу «Загрузка данных»; follow — чтобы получить сообщения."""
    return client.post(
        reverse("upload_excel"),
        {"file_type": file_type, "excel_file": SimpleUploadedFile(name, content)},
        follow=True,
    )


def messages_text(response):
    """Тексты сообщений Django на странице ответа."""
    return [str(m) for m in response.context["messages"]]
