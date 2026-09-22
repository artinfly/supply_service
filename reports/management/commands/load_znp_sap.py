"""
Команда загрузки заявок на платёж (ЗнП) из системы SAP.

Импортирует файл в staging-таблицу и нормализует данные
в рабочей таблице в одной транзакции. При ошибке — полный откат.

Особенности:
- Заявки перезаписываются целиком (без истории изменений)
- Нет привязки к позициям договоров по хешу
- Импортируются только заявки типа ГОЗ

Использование:
    python manage.py load_znp_sap <путь к файлу>
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from reports.models import SystemEvent
from reports.services.excel_import import import_znp_sap
from reports.services.normalize import normalize_znp_sap


class Command(BaseCommand):
    """Загрузка заявок на платёж из выгрузки SAP."""

    help = "Загрузка заявок ЗнП (SAP) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx")

    def handle(self, *args, **options):
        """Импортирует файл и нормализует данные в одной транзакции."""
        with transaction.atomic():
            loaded = import_znp_sap(options["filepath"])
            self.stdout.write(f"Загружено строк: {loaded}")

            result = normalize_znp_sap()
            self.stdout.write(result)

        SystemEvent.objects.update_or_create(
            event_key="sap_load",
            defaults={"event_time": timezone.now()},
        )
