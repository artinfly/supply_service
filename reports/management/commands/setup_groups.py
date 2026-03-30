from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = 'Создаёт группы пользователей: viewer, operator'

    def handle(self, *args, **kwargs):
        for name in ('viewer', 'operator'):
            Group.objects.get_or_create(name=name)
        self.stdout.write('Группы созданы: viewer, operator')