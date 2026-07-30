# Фильтр intspace для шаблонов: разбивает число на разряды (1234567 -> 1 234 567).
from django import template

register = template.Library()


@register.filter
def intspace(value):
    if value is None:
        return "0"
    try:
        num = float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return value
    return f"{num:,.2f}".replace(",", " ").replace(".", ",")
