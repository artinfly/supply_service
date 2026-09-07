"""
Модуль для вычисления crc32-хеша и перепривязки заявок к договорам.
Хеш используется для идентификации позиции договора по четырём полям:
ИГК, контрагент, договор, этап графика.

ВАЖНО: Алгоритм вычисления хеша не должен меняться после первого запуска в production,
иначе все существующие привязки станут невалидными.
"""

import logging
from zlib import crc32

from django.db import connection, transaction

logger = logging.getLogger(__name__)


def contract_hash(igk, c_agent, contract, stage):
    """
    Вычисляет crc32-хеш от конкатенации полей.
    Возвращает беззнаковое 32-битное число (0..2^32-1).

    ВНИМАНИЕ: Алгоритм зафиксирован! Изменение приведет к потере всех привязок.
    """
    # Приводим к строке и объединяем
    key = f"{igk or ''}{c_agent or ''}{contract or ''}{stage or ''}".encode("utf-8")
    # crc32 возвращает знаковое число, поэтому маскируем
    return crc32(key) & 0xFFFFFFFF


def relink_znp_parents():
    """
    Обновляет parent_id в znp_data, связывая заявки с позициями договоров.
    Сначала устанавливает parent_id по совпадению crc32_hash.
    Затем сбрасывает parent_id для тех заявок, у которых нет соответствующей позиции.
    Выполняется в транзакции для атомарности.

    Возвращает строку со статистикой: сколько заявок привязано и сколько без привязки.
    """
    with transaction.atomic(), connection.cursor() as cur:
        # Обновляем parent_id для заявок, у которых есть совпадение
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
        linked_count = cur.rowcount

        # Сбрасываем parent_id для заявок без совпадения
        cur.execute("""
            UPDATE znp_data z
            SET parent_id = NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM igk_stat_data i WHERE i.crc32_hash = z.crc32_hash
            )
        """)
        unlinked_count = cur.rowcount

        logger.info(
            f"Перепривязка заявок: привязано {linked_count}, без привязки {unlinked_count}"
        )

    return (
        f"привязано заявок: {linked_count}, без привязки к договору: {unlinked_count}"
    )
