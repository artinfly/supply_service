"""
Сигналы для автоматического создания профиля пользователя.

При создании нового пользователя (User) автоматически создаётся
связанная запись в модели Profile (расширение пользователя).
Используется стандартный сигнал post_save.
"""

import logging

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Создаёт профиль для нового пользователя.

    Сигнал срабатывает после сохранения модели User.
    Если пользователь только что создан (created=True),
    вызывается get_or_create для Profile, чтобы избежать дублирования.
    """
    if created:
        profile, was_created = Profile.objects.get_or_create(user=instance)
        if was_created:
            logger.info(f"Создан профиль для пользователя {instance.username}")
        else:
            # Теоретически не должно происходить, но на всякий случай логируем
            logger.warning(
                f"Профиль для пользователя {instance.username} уже существовал "
                f"(повторный вызов сигнала)"
            )
