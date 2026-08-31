"""
Команда загрузки заявок на платёж (ЗнП) из системы SAP.

Выполняет два шага в одной транзакции:
1. Импорт строк файла в staging-таблицу (staging_znp_sap_excel)
2. Нормализация: перенос данных в рабочую таблицу (znp_data_sap)

От загрузки договоров отличается:
- Нет истории изменений (заявки SAP перезаписываются целиком)
- Нет привязки по хешу (заявки не связаны с позициями договоров)
- При импорте отфильтровываются заявки, кроме ГОЗ

При ошибке на любом шаге транзакция откатывается — база остаётся прежней.

Использование:
    python manage.py load_znp_sap <путь к файлу>

После успешной загрузки записывается системное событие "sap_load".
Оно отображается на странице сводки заявок SAP («данные загружены ...»).
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
        # Единственный аргумент — путь к файлу .xlsx
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        """
        Импортирует файл и нормализует данные в одной транзакции.

        Шаги:
        1. Импорт строк файла в staging-таблицу (отбираются только ГОЗ)
        2. Нормализация: перенос из staging в рабочую таблицу

        Если нормализация падает — откатывается и импорт.
        """
        with transaction.atomic():
            # Шаг 1: читаем файл в staging_znp_sap_excel (только ГОЗ)
            loaded = import_znp_sap(options["filepath"])
            self.stdout.write(f"загружено строк: {loaded}")
            # Шаг 2: переносим из staging в рабочую таблицу
            self.stdout.write(normalize_znp_sap())

        # Записываем время последней загрузки — отображается на странице
        # сводки заявок SAP как подсказка «данные загружены ...»
        SystemEvent.objects.update_or_create(
            event_key="sap_load", defaults={"event_time": timezone.now()}
        )
