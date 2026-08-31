"""
Команда загрузки договоров из файла Excel.

Выполняет два шага в одной транзакции:
1. Импорт строк файла в staging-таблицу (staging_excel)
2. Нормализация: перенос данных в рабочую таблицу (igk_stat_data),
   запись истории изменений и привязка заявок

При ошибке на любом шаге транзакция откатывается — база остаётся прежней.

Использование:
    python manage.py load_contracts <путь к файлу>

После успешной загрузки записывается системное событие
"contracts_load" с текущим временем.
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
        # Единственный аргумент — путь к файлу .xlsx
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        """
        Импортирует файл и нормализует данные в одной транзакции.

        Шаги:
        1. Импорт строк файла в staging-таблицу
        2. Нормализация: перенос в рабочую таблицу, история изменений,
           привязка заявок ФЗД по хешу

        Если нормализация падает — откатывается и импорт.
        """
        with transaction.atomic():
            # Шаг 1: читаем файл в staging_excel
            loaded = import_contracts(options["filepath"])
            self.stdout.write(f"загружено строк: {loaded}")
            # Шаг 2: переносим из staging в рабочую таблицу
            self.stdout.write(normalize_contracts())

        # Записываем время последней загрузки для отображения на страницах
        SystemEvent.objects.update_or_create(
            event_key="contracts_load", defaults={"event_time": timezone.now()}
        )
