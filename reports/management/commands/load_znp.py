"""
Команда загрузки заявок на платёж (ЗнП) из системы ФЗД.

Импортирует файл в staging-таблицу и нормализует данные
в рабочей таблице в одной транзакции. При ошибке — полный откат.

Особенности:
- Заявки привязываются к позициям договоров через crc32_hash
- Непривязанные заявки не отображаются на страницах

Использование:
    python manage.py load_znp <путь к файлу>
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from reports.models import SystemEvent
from reports.services.excel_import import import_znp
from reports.services.normalize import normalize_znp


class Command(BaseCommand):
    """Загрузка заявок на платёж из выгрузки ФЗД."""

    help = "Загрузка заявок ЗнП (ФЗД) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx")

    def handle(self, *args, **options):
        """Импортирует файл и нормализует данные в одной транзакции."""
        with transaction.atomic():
            loaded = import_znp(options["filepath"])
            self.stdout.write(f"Загружено строк: {loaded}")

            result = normalize_znp()
            self.stdout.write(result)

        SystemEvent.objects.update_or_create(
            event_key="znp_load",
            defaults={"event_time": timezone.now()},
        )
