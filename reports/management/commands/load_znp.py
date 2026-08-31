"""
Команда загрузки заявок на платёж (ЗнП) из системы ФЗД.

Выполняет два шага в одной транзакции:
1. Импорт строк файла в staging-таблицу (staging_znp_excel)
2. Нормализация: перенос данных в рабочую таблицу (znp_data)
   и привязка заявок к позициям договоров по хешу

От загрузки заявок SAP отличается:
- Есть привязка к позициям договоров (через crc32_hash)
- Заявки без привязки не попадают на страницы (все выборки через parent)

При ошибке на любом шаге транзакция откатывается — база остаётся прежней.

Использование:
    python manage.py load_znp <путь к файлу>

После успешной загрузки записывается системное событие "znp_load".
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
        # Единственный аргумент — путь к файлу .xlsx
        parser.add_argument("filepath", type=str)

    def handle(self, *args, **options):
        """
        Импортирует файл и нормализует данные в одной транзакции.

        Шаги:
        1. Импорт строк файла в staging-таблицу
        2. Нормализация: перенос в рабочую таблицу и привязка заявок
           к позициям договоров по хешу (ИГК + контрагент + договор + этап)

        Если нормализация падает — откатывается и импорт.
        """
        with transaction.atomic():
            # Шаг 1: читаем файл в staging_znp_excel
            loaded = import_znp(options["filepath"])
            self.stdout.write(f"загружено строк: {loaded}")
            # Шаг 2: переносим из staging в рабочую таблицу и привязываем
            # заявки к позициям договоров (родительская связь)
            self.stdout.write(normalize_znp())

        # Записываем время последней загрузки
        SystemEvent.objects.update_or_create(
            event_key="znp_load", defaults={"event_time": timezone.now()}
        )
