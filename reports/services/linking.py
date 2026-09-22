"""
Модуль привязки заявок к позициям договоров.

Использует хеш от ключевых полей позиции для связи
заявок (ЗнП) с позициями договоров без прямых внешних ключей.
"""

import hashlib

from django.db import connection


def contract_hash(igk, c_agent, contract, stage):
    """
    Вычисляет 64-битный хеш позиции договора для привязки заявок.

    Хеш строится из четырёх ключевых полей: ИГК, контрагент, договор, этап.
    Возвращает знаковое 64-битное целое, совместимое с BigIntegerField.
    """
    parts = [str(v) if v is not None else "" for v in (igk, c_agent, contract, stage)]
    digest = hashlib.md5("".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def relink_znp_parents():
    """
    Привязывает заявки к позициям договоров по хешу.

    Для каждого хеша выбирается позиция с минимальным pp_id.
    Заявки без совпадающего хеша получают parent_id = NULL.
    """
    with connection.cursor() as cur:
        # Привязка заявок к позициям по совпадающему хешу
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
        # Обнуление привязки для заявок без совпадений
        cur.execute("""
            UPDATE znp_data z
            SET parent_id = NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM igk_stat_data i
                WHERE i.crc32_hash = z.crc32_hash
            )
        """)
