from zlib import crc32


def contract_hash(igk, c_agent, contract, stage):
    raw = f"{igk}{c_agent}{contract}{stage}"
    return crc32(raw.encode())
