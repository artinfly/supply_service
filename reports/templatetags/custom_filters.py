"""
Пользовательские фильтры для шаблонов.

Использование в шаблонах:
    {% load custom_filters %}
    {{ value|intspace }}
"""

from django import template

register = template.Library()


@register.filter
def intspace(value):
    """
    Форматирует число в русском стиле.

    Примеры:
        1234567.89  → "1 234 567,89"
        1000        → "1 000,00"

    Для None возвращает "0". Для нечисловых значений возвращает как есть.
    """
    if value is None:
        return "0"
    try:
        num = float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return value
    return f"{num:,.2f}".replace(",", " ").replace(".", ",")
