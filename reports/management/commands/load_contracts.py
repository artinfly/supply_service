"""
Команда загрузки договоров из файла Excel.

Выполняет импорт в staging-таблицу и нормализацию данных
в рабочей таблице в одной транзакции. При ошибке — полный откат.

Использование:
    python manage.py load_contracts <путь к файлу>
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from reports.models import SystemEvent
from reports.services.excel_import import import_contracts
from reports.services.normalize import normalize_contracts


class Command(BaseCommand):
    """Загрузка договоров из файла выгрузки."""

    help = "Загрузка договоров из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx")

    def handle(self, *args, **options):
        """Импортирует файл и нормализует данные в одной транзакции."""
        with transaction.atomic():
            loaded = import_contracts(options["filepath"])
            self.stdout.write(f"Загружено строк: {loaded}")

            result = normalize_contracts()
            self.stdout.write(result)

        SystemEvent.objects.update_or_create(
            event_key="contracts_load",
            defaults={"event_time": timezone.now()},
        )
