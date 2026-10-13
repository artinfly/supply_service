"""Management command: сверка ключей ГК с полем «Договор/Дата», переименование и слияние дублей."""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import GozContractVat
from core.services.gk_key import key_from_contract

# Поля, которые переносятся при слиянии дублей
_DATA_FIELDS = ("enterprise", "order", "contract_date", "year", "product")


class Command(BaseCommand):
    """Сверяет ключ ГК с полем «Договор/Дата» (учитывает «спец…/N»), переименовывает записи и сливает дубли.

    Без --apply только показывает план изменений.
    """

    help = (
        "Сверяет ключ ГК с полем «Договор/Дата» (учитывает «спец…/N»), "
        "переименовывает записи и сливает дубли. Без --apply только показывает план."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Записать изменения в базу данных",
        )

    def handle(self, *args, **options):
        """Основная логика команды: переименование и слияние записей ГК."""
        apply = options["apply"]
        records = {r.igk: r for r in GozContractVat.objects.all()}
        renamed = merged = conflicts = 0

        for rec in sorted(records.values(), key=lambda r: r.id):
            if not rec.contract_date:
                continue
            expected = key_from_contract(rec.contract_date)
            if not expected or expected == rec.igk:
                continue

            other = records.get(expected)

            # Случай 1: записи с таким ключом ещё нет — переименовываем
            if other is None:
                self.stdout.write(f"ПЕРЕИМЕНОВАТЬ: {rec.igk!r} -> {expected!r}")
                renamed += 1
                if apply:
                    rec.igk = expected
                    rec.save(update_fields=["igk"])
                records.pop(rec.igk if not apply else expected, None)
                records[expected] = rec
                continue

            # Случай 2: запись уже есть — проверяем конфликты
            both_filled = [
                f
                for f in ("enterprise", "order", "contract_date")
                if getattr(rec, f)
                and getattr(other, f)
                and getattr(rec, f) != getattr(other, f)
            ]
            if both_filled:
                conflicts += 1
                self.stdout.write(
                    f"КОНФЛИКТ: {rec.igk!r} и {expected!r} заполнены по-разному "
                    f"({', '.join(both_filled)})"
                )
                continue

            # Случай 3: дубликат — сливаем данные и удаляем старую запись
            self.stdout.write(f"СЛИТЬ: {rec.igk!r} -> {expected!r} (дубль удаляется)")
            merged += 1
            if apply:
                with transaction.atomic():
                    # Переносим заполненные поля из other в rec
                    for f in _DATA_FIELDS:
                        if not getattr(rec, f) and getattr(other, f):
                            setattr(rec, f, getattr(other, f))
                    rec.vat_rate = other.vat_rate
                    other.delete()
                    rec.igk = expected
                    rec.save()
                records[expected] = rec
            records.pop(rec.igk if rec.igk != expected else None, None)

        # Находим записи без данных (предприятие/заказ/договор/год/изделие)
        empty = [
            r.igk
            for r in records.values()
            if not any(getattr(r, f) for f in _DATA_FIELDS)
        ]
        mode = "выполнено" if apply else "план (запустите с --apply)"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: переименовать {renamed}, слить {merged}, конфликтов {conflicts}"
            )
        )
        if empty:
            self.stdout.write(
                f"Записей без данных (предприятие/заказ/договор/год/изделие): {len(empty)}. "
                f"Первые: {', '.join(sorted(empty)[:15])}"
            )
