from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

class Command(BaseCommand):
    help = 'setup_groups'

    def handle(self, *args, **kwargs):
        Group.objects.get_or_create(name='viewer')
        Group.objects.get_or_create(name='operator')
        self.stdout.write('groups created: viewer, operator')
