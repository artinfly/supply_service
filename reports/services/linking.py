from zlib import crc32

from django.db import connection


def contract_hash(igk, c_agent, contract, stage):
    parts = [str(v) if v is not None else "" for v in (igk, c_agent, contract, stage)]
    return crc32("".join(parts).encode())


def relink_znp_parents():
    with connection.cursor() as cur:
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
        cur.execute("""
            UPDATE znp_data z
            SET parent_id = NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM igk_stat_data i
                WHERE i.crc32_hash = z.crc32_hash
            )
        """)
