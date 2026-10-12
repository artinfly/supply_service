from decimal import Decimal

from ..models import GozContractVat
from .gk_key import gk_base, gk_key, parse_gk_key

DEFAULT_VAT_RATE = Decimal("22.0")


def directory_index():
    """(по ключу, по первым 4 цифрам только для старых записей без «/сб»)."""
    by_key, legacy = {}, {}
    for rec in GozContractVat.objects.all():
        by_key[rec.igk] = rec
        if "/" not in rec.igk:
            legacy.setdefault(gk_base(rec.igk), []).append(rec)
    return by_key, legacy


def find_gk(label, index):
    """Запись справочника для ГК из архива/файла или None."""
    by_key, legacy = index
    key = gk_key(label)
    rec = by_key.get(key)
    if rec:
        return rec
    candidates = legacy.get(gk_base(key), [])
    return candidates[0] if len(candidates) == 1 else None


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
    Старая запись без сб (только «6066») переименовывается в новый ключ,
    если по этим 4 цифрам она единственная.
    Возвращает (добавлено, обновлено, ошибки).
    """
    by_key, legacy = directory_index()
    added = updated = 0
    errors = []

    for n, row in enumerate(rows, 1):
        cells = [_cell(c) for c in list(row)[:4]]
        cells += [""] * (4 - len(cells))
        _num, enterprise, order, contract = cells

        if not any(cells[1:]) or _is_header(cells):
            continue

        key = parse_gk_key(contract)
        if not key:
            errors.append(f"строка {n}: в «{contract[:40]}» не найден ГК вида игк/111сб")
            continue

        fields = {
            "enterprise": enterprise[:255] or None,
            "order": order[:100] or None,
            "contract_date": contract[:255] or None,
        }

        rec = by_key.get(key)
        if rec is None:
            candidates = legacy.get(gk_base(key), [])
            if len(candidates) == 1:
                rec = candidates[0]
                legacy[gk_base(key)] = []
                by_key.pop(rec.igk, None)
                rec.igk = key
                by_key[key] = rec

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
