"""Management command: загрузка заявок ЗнП (ФЗД) из Excel-файла."""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import SystemEvent
from core.services.importing.excel_import import import_znp
from core.services.importing.normalize import normalize_znp


class Command(BaseCommand):
    """Загружает файл заявок ФЗД в staging-таблицу и нормализует данные в рабочие таблицы.

    Все операции выполняются в одной транзакции. После успешной загрузки
    обновляется время последнего импорта в SystemEvent.
    """

    help = "Загрузка заявок ЗнП (ФЗД) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx")

    def handle(self, *args, **options):
        """Основная логика: импорт → нормализация → обновление SystemEvent."""
        with transaction.atomic():
            loaded = import_znp(options["filepath"])
            self.stdout.write(f"Загружено строк: {loaded}")

            result = normalize_znp()
            self.stdout.write(result)

        # Обновляем время последней загрузки заявок ФЗД (вне транзакции импорта)
        SystemEvent.objects.update_or_create(
            event_key="znp_load",
            defaults={"event_time": timezone.now()},
        )
