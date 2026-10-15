"""Общие помощники для HTML-страниц: базовый контекст, проверка суперпользователя."""

from functools import wraps

from django.contrib import messages
from django.db import connection
from django.shortcuts import redirect

from ..services.queries import YEARS, distinct_cfo, distinct_igk_suffixes


def base_context():
    """Контекст, который нужен каждой странице: годы для меню и фильтров."""
    return {
        "years": YEARS,
        # Пары (2025, "y25") — для чекбоксов годов в фильтрах реестров
        "year_cols": [(y, f"y{str(y)[2:]}") for y in YEARS],
        "last_year": YEARS[-1],
    }


def superuser_required(view_func):
    """Декоратор: действие только для суперпользователей.

    Используется для загрузки справочника ГК из файла (массовая замена данных).
    Ручная правка записей доступна всем с доступом к «Анализу ГОЗ». Обычный
    пользователь возвращается на страницу раздела с сообщением об ошибке.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(
                request, "Загружать справочник ГК из файла могут только суперпользователи."
            )
            return redirect("goz_report")
        return view_func(request, *args, **kwargs)

    return wrapper


def igk_and_cfo_lists():
    """Списки для фильтров реестров: ИГК (последние 4 цифры) и ЦФО."""
    with connection.cursor() as cur:
        cur.execute(distinct_igk_suffixes())
        igk_list = [r[0] for r in cur.fetchall()]
        cur.execute(distinct_cfo())
        cfo_list = [r[0] for r in cur.fetchall()]
    return igk_list, cfo_list
