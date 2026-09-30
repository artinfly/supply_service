from django.core.management.base import BaseCommand

from reports.services.excel_import import import_sum_report


class Command(BaseCommand):
    help = "Загрузка Краткой справки в staging-таблицу"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к файлу Excel")

    def handle(self, *args, **options):
        filepath = options["filepath"]
        try:
            count = import_sum_report(filepath)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Краткая справка загружена в staging. Обработано строк: {count}"
                )
            )
        except Exception as e:
            raise Exception(f"Ошибка парсинга Краткой справки: {e}")
