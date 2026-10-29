"""Фильтры шаблонов для подписи пользователя."""

from django import template

register = template.Library()


@register.filter
def short_name(user):
    """«Иванов И.П.» (отчество — из профиля); без фамилии — логин."""
    if not user.last_name:
        return user.username
    profile = getattr(user, "profile", None)  # профиля может не быть
    patronymic = profile.patronymic if profile else ""
    initials = "".join(f"{part[0]}." for part in (user.first_name, patronymic) if part)
    return f"{user.last_name} {initials}".strip()
