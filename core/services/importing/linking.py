"""Привязка заявок ФЗД к позициям договоров по хешу."""

from zlib import crc32

from django.db import connection


def contract_hash(igk, c_agent, contract, stage):
    """Вычисляет хеш привязки заявки к договору.

    Один и тот же хеш считается для позиции договора (normalize_contracts)
    и для заявки ФЗД (import_znp); совпадение хешей = заявка этой позиции.

    Ограничения (менять осторожно — потребуется перезагрузить и договоры, и ЗнП):
      * поля склеиваются без разделителя: «12»+«3» и «1»+«23» дают одно и то же;
      * CRC32 — 32-битный хеш, на десятках тысяч строк случайные совпадения
        возможны. При совпадении заявка привяжется к позиции с меньшим pp_id.

    Args:
        igk: код ИГК
        c_agent: контрагент
        contract: номер договора
        stage: этап

    Returns:
        int: CRC32 хеш
    """
    parts = [str(v) if v is not None else "" for v in (igk, c_agent, contract, stage)]
    return crc32("".join(parts).encode())


def relink_znp_parents():
    """Обновляет связи заявок ФЗД с позициями договоров.

    1. Привязывает заявки к позиции с минимальным pp_id при совпадении хеша.
    2. Сбрасывает parent_id в NULL, если совпадение не найдено.
    """
    with connection.cursor() as cur:
        # Шаг 1: Привязка по совпадению хеша
        cur.execute("""
            UPDATE znp_data z
            SET parent_id = matched.pp_id
            FROM (
                SELECT crc32_hash, MIN(pp_id) AS pp_id
                FROM igk_stat_data
                GROUP BY crc32_hash
            ) matched
            WHERE z.crc32_hash = matched.crc32_hash
        """)

        # Шаг 2: Сброс связей для заявок без совпадений
        cur.execute("""
            UPDATE znp_data z
            SET parent_id = NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM igk_stat_data i
                WHERE i.crc32_hash = z.crc32_hash
            )
        """)
