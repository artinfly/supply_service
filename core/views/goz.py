"""Раздел «Анализ ГОЗ»: отчёт по архиву ЕИС ГОЗ и справочник ГК.

Формирование отчёта идёт в два шага на одной странице:
  1. Пользователь загружает ZIP с .xls. Архив сохраняется во временный файл,
     на экран выводится список ГК со ставками НДС из справочника.
  2. Пользователь правит ставки/год/изделие и нажимает «Сформировать отчёт»
     (AJAX). Архив читается повторно, отчёт отдаётся файлом, временный
     архив удаляется.
Путь к временному архиву хранится в сессии пользователя: так шаг 2 может
открыть только свой архив, а не любой файл из временной папки.
"""

import json
import logging
import os
import tempfile
import time
import zipfile
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import GozContractVat
from ..services.goz import analysis as goz_analysis
from ..services.goz.gk_directory import (
    DEFAULT_VAT_RATE,
    directory_index,
    find_gk,
    import_extended_rows,
    import_simple_values,
    is_extended_directory,
    read_sheet_rows,
    simple_values_from_docx,
    simple_values_from_rows,
)
from ..services.goz.gk_key import gk_key
from ..services.reports.excel import xlsx_response
from .common import base_context, superuser_required

logger = logging.getLogger(__name__)

# Временные архивы раздела: префикс в имени позволяет чистить только свои файлы
_TEMP_PREFIX = "goz_"
_TEMP_MAX_AGE = 24 * 60 * 60  # архивы старше суток удаляются при следующей загрузке
_SESSION_KEY = "goz_temp_zip"


# --- Временный архив между шагами 1 и 2 ---


def _remove_file(path):
    """Удаляет файл, если он есть; ошибки удаления не критичны."""
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            logger.warning("Не удалось удалить временный файл %s", path)


def _cleanup_old_archives():
    """Удаляет брошенные архивы (загрузили, но отчёт так и не сформировали)."""
    folder = tempfile.gettempdir()
    now = time.time()
    for name in os.listdir(folder):
        if name.startswith(_TEMP_PREFIX) and name.endswith(".zip"):
            path = os.path.join(folder, name)
            try:
                if now - os.path.getmtime(path) > _TEMP_MAX_AGE:
                    os.unlink(path)
            except OSError:
                pass


def _save_archive(request, uploaded):
    """Сохраняет загруженный ZIP во временный файл и запоминает путь в сессии."""
    _cleanup_old_archives()
    _remove_file(request.session.pop(_SESSION_KEY, None))  # предыдущий архив этого пользователя

    with tempfile.NamedTemporaryFile(delete=False, prefix=_TEMP_PREFIX, suffix=".zip") as tmp:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
    request.session[_SESSION_KEY] = tmp.name
    return tmp.name


def _session_archive(request):
    """Путь к архиву текущего пользователя из шага 1 или None."""
    path = request.session.get(_SESSION_KEY)
    return path if path and os.path.exists(path) else None


# --- Справочник: сохранение ставок с шага 2 ---


def _to_vat(value):
    """Ставка НДС из формы («20», «20,0») в Decimal; при ошибке — 22%."""
    try:
        return Decimal(str(value).replace(",", "."))
    except Exception:
        return DEFAULT_VAT_RATE


def _save_gk_to_directory(gk_data):
    """Сохраняет ставку НДС, год и изделие по каждому ГК архива в справочник.

    Args:
        gk_data: {ключ ГК: {"vat": ..., "year": ..., "product": ...}} из формы шага 2

    Returns:
        список текстов ошибок
    """
    errors = []
    index = directory_index()

    for label, item in gk_data.items():
        key = gk_key(label)
        defaults = {"vat_rate": _to_vat(item.get("vat"))}

        # Пустые год/изделие не затирают уже заполненные в справочнике
        year = str(item.get("year") or "").strip()
        product = str(item.get("product") or "").strip()
        if year:
            defaults["year"] = year
        if product:
            defaults["product"] = product

        try:
            rec = find_gk(key, index)
            if rec:
                for name, value in defaults.items():
                    setattr(rec, name, value)
                rec.save()
            else:
                rec = GozContractVat.objects.create(igk=key, **defaults)
            index[key] = rec
        except Exception as e:
            errors.append(f"{key}: {e}")

    return errors


# --- Страница раздела ---


def _archive_gk_list(archive_path):
    """Список ГК архива для шага 1: данные из справочника или «новый»."""
    index = directory_index()
    gk_list = []

    for zip_igk, _plan, _fact in goz_analysis.read_archive(archive_path):
        rec = find_gk(zip_igk, index)
        gk_list.append(
            {
                # Найденный ГК показываем ключом справочника («9741/255сб 136»,
                # хотя в имени файла было «9741_136»), новый — как в имени файла
                "igk": rec.igk if rec else zip_igk,
                "enterprise": (rec and rec.enterprise) or "",
                "order": (rec and rec.order) or "",
                "year": (rec and rec.year) or "",
                "product": (rec and rec.product) or "",
                "vat_rate": float(rec.vat_rate if rec else DEFAULT_VAT_RATE),
                "is_new": rec is None,
            }
        )
    return gk_list


def _build_report(archive_path, gk_data):
    """Шаг 2: отчёт по архиву со ставками и изделиями из формы."""
    index = directory_index()
    contracts = []
    extras = {}  # контрагент и заказ из справочника — колонки после «ГК»

    for zip_igk, plan, fact in goz_analysis.read_archive(archive_path):
        rec = find_gk(zip_igk, index)
        # Та же подпись ГК, что на шаге 1: по ней из формы берутся НДС и изделие
        label = rec.igk if rec else zip_igk
        contracts.append((label, plan, fact))
        if rec:
            extras[label] = {"agent": rec.enterprise or "", "order": rec.order or ""}

    vat_rates = {k: v.get("vat") for k, v in gk_data.items()}
    products = {k: (v.get("product") or "").strip() for k, v in gk_data.items()}
    return goz_analysis.build_report(contracts, vat_rates, products, extras)


@login_required
def goz_report(request):
    """Страница «Анализ ГОЗ»: справочник ГК, загрузка архива и формирование отчёта."""
    ctx = base_context()
    ctx["directory_list"] = GozContractVat.objects.all().order_by("igk", "year")

    if request.method == "POST":
        gk_data_json = request.POST.get("gk_data")
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        # --- Шаг 2: сформировать отчёт ---
        if gk_data_json:
            archive_path = _session_archive(request)
            if archive_path is None:
                text = "Архив не найден или устарел. Загрузите архив заново."
                if is_ajax:
                    return JsonResponse({"error": text}, status=400)
                messages.error(request, text)
                return redirect("goz_report")

            try:
                gk_data = json.loads(gk_data_json)

                if request.POST.get("save_to_dir") == "on":
                    for err in _save_gk_to_directory(gk_data):
                        messages.warning(request, f"Не сохранено в справочник: {err}")

                data = _build_report(archive_path, gk_data)
                return xlsx_response(data, "Анализ_ГОЗ")
            except Exception as e:
                logger.exception("Ошибка формирования отчёта «Анализ ГОЗ»")
                if is_ajax:
                    return JsonResponse(
                        {"error": f"Ошибка формирования отчёта: {e}"}, status=400
                    )
                messages.error(request, f"Ошибка формирования отчёта: {e}")
            finally:
                # Архив одноразовый: и после успеха, и после ошибки нужен новый
                _remove_file(request.session.pop(_SESSION_KEY, None))

        # --- Шаг 1: загрузить архив ---
        elif request.FILES.get("archive"):
            archive_path = _save_archive(request, request.FILES["archive"])
            try:
                ctx["gk_list"] = _archive_gk_list(archive_path)
                ctx["temp_zip_path"] = os.path.basename(archive_path)
                ctx["step2"] = True
                # Разные ИГК с одинаковыми последними 4 цифрами склеиваются в один ключ
                for key, nums in goz_analysis.same_key_numbers(archive_path).items():
                    messages.warning(
                        request,
                        f"ГК «{key}»: в архиве разные ИГК с одинаковыми последними "
                        f"4 цифрами ({', '.join(nums)}). В отчёте они не различаются.",
                    )
            except zipfile.BadZipFile:
                messages.error(request, "Файл не является ZIP-архивом")
            except Exception as e:
                logger.exception("Ошибка чтения архива «Анализ ГОЗ»")
                messages.error(request, f"Ошибка обработки архива: {e}")

            if "step2" not in ctx:
                _remove_file(request.session.pop(_SESSION_KEY, None))

    if "step2" not in ctx:
        ctx["default_vat_rate"] = float(DEFAULT_VAT_RATE)

    return render(request, "goz_report.html", ctx)


# --- Справочник ГК: загрузка из файла и ручная правка ---


@login_required
@superuser_required
def upload_gk_directory(request):
    """Загрузка справочника ГК из Word (.docx) или Excel (.xlsx, .xls). Только суперпользователь."""
    if request.method != "POST" or not request.FILES.get("doc_file"):
        return redirect("goz_report")

    file = request.FILES["doc_file"]
    ext = os.path.splitext(file.name)[1].lower()

    try:
        if ext == ".docx":
            added, existing, errors = import_simple_values(simple_values_from_docx(file))
            summary = f"Добавлено: {added}, уже были в справочнике: {existing}."
        elif ext in (".xlsx", ".xls"):
            rows = read_sheet_rows(file, ext)
            if is_extended_directory(rows):
                added, updated, errors = import_extended_rows(rows)
                summary = f"Добавлено: {added}, обновлено: {updated}."
            else:
                added, existing, errors = import_simple_values(
                    simple_values_from_rows(rows)
                )
                summary = f"Добавлено: {added}, уже были в справочнике: {existing}."
        else:
            messages.error(
                request, "Неподдерживаемый формат. Используйте .docx, .xlsx или .xls"
            )
            return redirect("goz_report")
    except Exception as e:
        logger.exception("Ошибка разбора файла справочника ГК %s", file.name)
        messages.error(request, f"Ошибка разбора файла: {e}")
        return redirect("goz_report")

    for err in errors[:5]:
        messages.warning(request, f"Пропущено: {err}")
    if len(errors) > 5:
        messages.warning(request, f"…и ещё ошибок: {len(errors) - 5}")

    messages.success(request, f"Справочник обновлён. {summary}")
    return redirect("goz_report")


@login_required
def gk_directory_save(request):
    """Сохранение записи справочника ГК из формы (создание или правка).

    Доступно всем, у кого есть доступ к разделу «Анализ ГОЗ» (право проверяет
    middleware). Загрузка справочника из файла — только суперпользователю.
    """
    if request.method == "POST":
        record_id = request.POST.get("record_id", "").strip()
        igk = gk_key(request.POST.get("igk", ""))
        enterprise = request.POST.get("enterprise", "").strip()
        order = request.POST.get("order", "").strip()
        contract_date = request.POST.get("contract_date", "").strip()
        year = request.POST.get("year", "").strip()
        product = request.POST.get("product", "").strip()

        if not igk:
            messages.error(request, "Поле «ГК» обязательно для заполнения.")
            return redirect("goz_report")

        fields = {
            "igk": igk,
            "enterprise": enterprise or None,
            "order": order or None,
            "contract_date": contract_date or None,
            "year": year or None,
            "product": product or None,
            "vat_rate": _to_vat(request.POST.get("vat_rate", "22.0").strip()),
        }

        try:
            if record_id:
                updated = GozContractVat.objects.filter(id=record_id).update(**fields)
                if updated:
                    messages.success(request, f"Запись для ГК «{igk}» обновлена.")
                else:
                    messages.error(request, "Запись не найдена.")
            else:
                GozContractVat.objects.create(**fields)
                messages.success(request, f"ГК «{igk}» добавлен в справочник.")
        except IntegrityError:
            messages.error(request, f"ГК «{igk}» уже есть в справочнике.")
        except Exception as e:
            logger.exception("Ошибка сохранения записи справочника ГК")
            messages.error(request, f"Ошибка сохранения: {e}")

    return redirect("goz_report")


@login_required
def gk_directory_delete(request):
    """Удаление записи справочника ГК (доступно всем с доступом к разделу)."""
    if request.method == "POST":
        record_id = request.POST.get("record_id", "").strip()
        if record_id:
            rec = GozContractVat.objects.filter(id=record_id).first()
            if rec is None:
                messages.error(request, "Запись не найдена.")
            else:
                rec.delete()
                messages.success(request, f"Запись для ГК «{rec.igk}» удалена.")

    return redirect("goz_report")
