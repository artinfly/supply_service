"""Работа со справочником ГК: чтение, поиск, импорт расширенных данных."""

from decimal import Decimal

from ..models import GozContractVat
from .gk_key import gk_key, key_from_contract

# Ставка НДС по умолчанию для новых записей справочника
DEFAULT_VAT_RATE = Decimal("22.0")


# --- Чтение справочника ---


def directory_index():
    """Возвращает словарь {ключ ГК: запись} для быстрого поиска.

    Ключи нормализованы: «1234» и «1234/34сб» — разные ГК.
    """
    return {rec.igk: rec for rec in GozContractVat.objects.all()}


def find_gk(label, index):
    """Ищет запись справочника по метке из архива/файла (точное совпадение ключа).

    Args:
        label: метка ГК из файла (например, «1234/34сб»)
        index: словарь {ключ: запись} от directory_index()

    Returns:
        GozContractVat или None, если ключ не найден
    """
    return index.get(gk_key(label))


# --- Вспомогательные функции для импорта ---


def _cell(value):
    """Преобразует значение ячейки в строку: None → '', float без дробной части → int."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _is_header(cells):
    """Проверяет, является ли строка заголовком таблицы (содержит «предприятие» или «заказ»)."""
    low = [c.lower() for c in cells]
    return any("предприятие" in c for c in low) or any(c == "заказ" for c in low)


# --- Импорт расширенного справочника ---


def import_extended_rows(rows):
    """Импортирует расширенный справочник ГК из файла с колонками: № | Предприятие | Заказ | Договор/Дата.

    ГК извлекается из поля «Договор/Дата» (например, «…6066/162сб/137 от …» → «6066/162сб»).
    ГК «6066» и «6066/162сб» считаются разными записями.

    Args:
        rows: итератор строк файла (списки значений ячеек)

    Returns:
        tuple: (добавлено, обновлено, список_ошибок)
    """
    by_key = directory_index()
    added = updated = 0
    errors = []

    for n, row in enumerate(rows, 1):
        # Берём первые 4 колонки, дополняем пустыми при необходимости
        cells = [_cell(c) for c in list(row)[:4]]
        cells += [""] * (4 - len(cells))
        _num, enterprise, order, contract = cells

        # Пропускаем пустые строки и заголовки
        if not any(cells[1:]) or _is_header(cells):
            continue

        # Извлекаем ключ ГК из поля «Договор/Дата»
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
                # Обновляем существующую запись
                for name, value in fields.items():
                    setattr(rec, name, value)
                rec.save()
                updated += 1
            else:
                # Создаём новую запись со ставкой НДС по умолчанию
                by_key[key] = GozContractVat.objects.create(
                    igk=key, vat_rate=DEFAULT_VAT_RATE, **fields
                )
                added += 1
        except Exception as e:
            errors.append(f"строка {n} ({key}): {e}")

    return added, updated, errors
