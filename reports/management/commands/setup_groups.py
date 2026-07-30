# Создаёт группы viewer и operator. Запускается один раз при развёртывании.
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Создаёт группы пользователей: viewer, operator"

    def handle(self, *args, **kwargs):
        for name in ("viewer", "operator"):
            Group.objects.get_or_create(name=name)
        self.stdout.write("Группы созданы: viewer, operator")
