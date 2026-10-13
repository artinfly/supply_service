"""Management command: загрузка договоров из Excel-файла."""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import SystemEvent
from core.services.excel_import import import_contracts
from core.services.normalize import normalize_contracts


class Command(BaseCommand):
    """Загружает файл договоров в staging-таблицу и нормализует данные в рабочие таблицы.

    Все операции выполняются в одной транзакции. После успешной загрузки
    обновляется время последнего импорта в SystemEvent.
    """

    help = "Загрузка договоров из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx")

    def handle(self, *args, **options):
        """Основная логика: импорт → нормализация → обновление SystemEvent."""
        with transaction.atomic():
            loaded = import_contracts(options["filepath"])
            self.stdout.write(f"Загружено строк: {loaded}")

            result = normalize_contracts()
            self.stdout.write(result)

        # Обновляем время последней загрузки договоров (вне транзакции импорта)
        SystemEvent.objects.update_or_create(
            event_key="contracts_load",
            defaults={"event_time": timezone.now()},
        )
