"""manage.py seed_demo — заполнить базу вымышленными договорами и заявками."""

from django.core.management.base import BaseCommand

from apps.demo.generator import seed


class Command(BaseCommand):
    help = "Вымышленные договоры, заявки ФЗД и SAP (заменяют загруженные данные)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--contracts", type=int, default=150, help="число договоров"
        )
        parser.add_argument("--seed", type=int, default=1, help="повторяемый результат")

    def handle(self, *args, **options):
        seed(options["contracts"], options["seed"], stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Демо-данные загружены"))
