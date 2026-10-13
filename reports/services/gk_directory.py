from decimal import Decimal

from ..models import GozContractVat
from .gk_key import gk_key, key_from_contract

DEFAULT_VAT_RATE = Decimal("22.0")


def directory_index():
    """{ключ ГК: запись}. «1234» и «1234/34сб» — разные ГК."""
    return {rec.igk: rec for rec in GozContractVat.objects.all()}


def find_gk(label, index):
    """Запись справочника для ГК из архива/файла (только точное совпадение ключа) или None."""
    return index.get(gk_key(label))


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _is_header(cells):
    low = [c.lower() for c in cells]
    return any("предприятие" in c for c in low) or any(c == "заказ" for c in low)


def import_extended_rows(rows):
    """Файл: № | Предприятие | Заказ | Договор/Дата.

    ГК берётся из договора («…6066/162сб/137 от …» -> «6066/162сб»).
    ГК «6066» и «6066/162сб» считаются разными записями.
    Возвращает (добавлено, обновлено, ошибки).
    """
    by_key = directory_index()
    added = updated = 0
    errors = []

    for n, row in enumerate(rows, 1):
        cells = [_cell(c) for c in list(row)[:4]]
        cells += [""] * (4 - len(cells))
        _num, enterprise, order, contract = cells

        if not any(cells[1:]) or _is_header(cells):
            continue

        key = key_from_contract(contract)
        if not key:
            errors.append(f"строка {n}: в «{contract[:40]}» не найден номер ГК")
            continue

        fields = {
            "enterprise": enterprise[:255] or None,
            "order": order[:100] or None,
            "contract_date": contract[:255] or None,
        }

        rec = by_key.get(key)

        try:
            if rec:
                for name, value in fields.items():
                    setattr(rec, name, value)
                rec.save()
                updated += 1
            else:
                by_key[key] = GozContractVat.objects.create(
                    igk=key, vat_rate=DEFAULT_VAT_RATE, **fields
                )
                added += 1
        except Exception as e:
            errors.append(f"строка {n} ({key}): {e}")

    return added, updated, errors
