# Загрузка заявок ЗнП (ФЗД): файл читается в staging и сразу разбирается.
# Оба шага в одной транзакции — при ошибке база остаётся прежней.
from django.core.management.base import BaseCommand
from django.db import transaction

from reports.services.excel_import import import_znp
from reports.services.normalize import normalize_znp


class Command(BaseCommand):
    help = "Загрузка заявок ЗнП (ФЗД) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        with transaction.atomic():
            loaded = import_znp(options["filepath"])
            self.stdout.write(f"загружено строк: {loaded}")
            self.stdout.write(normalize_znp())
