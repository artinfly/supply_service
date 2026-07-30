# Загрузка заявок ЗнП (ФЗД): чтение файла и разбор одной транзакцией.
from django.core.management.base import BaseCommand
from django.db import transaction

from reports.management.commands.import_znp_excel import Command as ImportCommand
from reports.services.normalize import normalize_znp


class Command(BaseCommand):
    help = "Загрузка заявок ЗнП (ФЗД) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        with transaction.atomic():
            loader = ImportCommand()
            loader.stdout = self.stdout
            loader.style = self.style
            loader.handle(filepath=options["filepath"])
            self.stdout.write(normalize_znp())
