"""Management command: загрузка заявок ЗнП (SAP) из Excel-файла."""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import SystemEvent
from core.services.importing.excel_import import import_znp_sap
from core.services.importing.normalize import normalize_znp_sap


class Command(BaseCommand):
    """Загружает файл заявок SAP в staging-таблицу и нормализует данные в рабочие таблицы.

    Все операции выполняются в одной транзакции. После успешной загрузки
    обновляется время последнего импорта в SystemEvent.
    """

    help = "Загрузка заявок ЗнП (SAP) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx или .xls")

    def handle(self, *args, **options):
        """Основная логика: импорт → нормализация → обновление SystemEvent."""
        with transaction.atomic():
            loaded = import_znp_sap(options["filepath"])
            self.stdout.write(f"Загружено строк: {loaded}")

            result = normalize_znp_sap()
            self.stdout.write(result)

        # Обновляем время последней загрузки заявок SAP (вне транзакции импорта)
        SystemEvent.objects.update_or_create(
            event_key="sap_load",
            defaults={"event_time": timezone.now()},
        )
