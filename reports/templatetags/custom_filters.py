"""
Пользовательские фильтры для шаблонов.

Используется в шаблонах как:
    {{ value|intspace }}

Фильтр `intspace` форматирует числа в русском стиле:
- Разделители тысяч — пробелы
- Десятичный разделитель — запятая
- Два знака после запятой

Примеры:
    1234567.89  → "1 234 567,89"
    1000        → "1 000,00"
    "1234,56"   → "1 234,56"
    -1234.5     → "-1 234,50"

Дополнительные фильтры:
    intspace0 — форматирует без десятичной части (целые числа).
"""

import math

from django import template

register = template.Library()


@register.filter
def intspace(value):
    """
    Форматирует число в русском стиле: пробелы между разрядами,
    запятая как десятичный разделитель, два знака после запятой.

    Если значение не является числом, возвращает его как есть.
    """
    if value is None:
        return "0,00"

    # Парсим значение
    try:
        # Если это строка, заменяем запятые на точки и убираем пробелы
        if isinstance(value, str):
            num = float(value.replace(",", ".").replace(" ", ""))
        else:
            num = float(value)
    except (ValueError, TypeError):
        return value

    # Проверяем на бесконечность и NaN
    if not math.isfinite(num):
        return str(num)

    # Форматируем с двумя знаками после запятой
    return f"{num:,.2f}".replace(",", " ").replace(".", ",")


@register.filter
def intspace0(value):
    """
    Форматирует число как целое (без десятичной части) в русском стиле.
    Пример: 1234.56 → "1 235" (округляет по математическим правилам)
    """
    if value is None:
        return "0"

    try:
        if isinstance(value, str):
            num = float(value.replace(",", ".").replace(" ", ""))
        else:
            num = float(value)
    except (ValueError, TypeError):
        return value

    if not math.isfinite(num):
        return str(num)

    # Округляем до целого и форматируем с пробелами
    return f"{round(num):,}".replace(",", " ")
