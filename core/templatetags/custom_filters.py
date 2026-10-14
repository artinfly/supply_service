"""Пользовательские фильтры шаблонов для форматирования чисел."""

from django import template

register = template.Library()


@register.filter
def intspace(value):
    """Форматирует число в русский формат: пробелы между тысячами, запятая для дробной части.

    Пример: 1234567.89 → '1 234 567,89'
    """
    if value is None:
        return "0"
    try:
        num = float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return value
    return f"{num:,.2f}".replace(",", " ").replace(".", ",")
