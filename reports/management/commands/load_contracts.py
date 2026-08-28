from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from reports.models import SystemEvent
from reports.services.excel_import import import_contracts
from reports.services.normalize import normalize_contracts


class Command(BaseCommand):
    help = "Загрузка договоров из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        with transaction.atomic():
            loaded = import_contracts(options["filepath"])
            self.stdout.write(f"загружено строк: {loaded}")
            self.stdout.write(normalize_contracts())
        SystemEvent.objects.update_or_create(
            event_key="contracts_load", defaults={"event_time": timezone.now()}
        )
