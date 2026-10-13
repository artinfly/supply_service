from django.core.management.base import BaseCommand

from reports.models import GozContractVat
from reports.services.gk_key import gk_key


class Command(BaseCommand):
    help = (
        "Приводит ГК в справочнике к формату игк/111сб (+ спец через пробел). "
        "Без --apply только показывает, что изменится."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="записать изменения")

    def handle(self, *args, **options):
        apply = options["apply"]
        taken = set(GozContractVat.objects.values_list("igk", flat=True))
        changed = conflicts = 0

        for rec in GozContractVat.objects.order_by("id"):
            new_key = gk_key(rec.igk)
            if new_key == rec.igk:
                continue

            if new_key in taken:
                conflicts += 1
                self.stdout.write(f"КОНФЛИКТ (ключ занят): {rec.igk!r} -> {new_key!r}")
                continue

            self.stdout.write(f"{rec.igk!r} -> {new_key!r}")
            changed += 1
            taken.discard(rec.igk)
            taken.add(new_key)

            if apply:
                rec.igk = new_key
                rec.save(update_fields=["igk"])

        mode = "изменено" if apply else "будет изменено (запустите с --apply)"
        self.stdout.write(self.style.SUCCESS(f"{mode}: {changed}, конфликтов: {conflicts}"))
