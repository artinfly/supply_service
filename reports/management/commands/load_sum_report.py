"""
Команда загрузки Краткой справки (SumReport) в staging-таблицу.

Краткая справка используется для формирования Excel-отчётов
«Обычная» и «Длинноцикловая» (см. services/sum_report.py).

Особенности:
- Данные загружаются в staging_sum_excel
- Импорт НЕ затрагивает рабочие таблицы договоров
- Используется как промежуточный шаг для последующей выгрузки

Использование:
    python manage.py load_sum_report <путь к файлу>
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from reports.models import SystemEvent
from reports.services.excel_import import import_sum_report


class Command(BaseCommand):
    """Загрузка Краткой справки в staging-таблицу."""

    help = "Загрузка Краткой справки (SumReport) из файла Excel"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу .xlsx")

    def handle(self, *args, **options):
        """Импортирует файл в staging_sum_excel одной транзакцией."""
        try:
            with transaction.atomic():
                loaded = import_sum_report(options["filepath"])
                self.stdout.write(f"Загружено строк: {loaded}")
        except Exception as e:
            raise CommandError(f"Ошибка загрузки Краткой справки: {e}") from e

        SystemEvent.objects.update_or_create(
            event_key="sum_report_load",
            defaults={"event_time": timezone.now()},
        )
