"""Единый формат ключа ГК в справочнике и в отчёте.

    игк                 6066
    игк/111сб           6066/162сб
    + спец (номер)      6066 5        6066/162сб 5

игк — последние 4 цифры номера ИГК, 111сб — номер сборочного контракта,
число после пробела — номер «спец…/N» из договора. «1234», «1234/34сб»
и «1234 5» — разные ГК.
"""

import re

_GK_RE = re.compile(r"(\d{4})(?!\d)\s*[/_\s\-]*\s*(\d+)\s*[сc]б", re.IGNORECASE)
_BASE_ONLY_RE = re.compile(r"^\s*(\d{4})(?:[\s_/\-]+(?:спец\D*?)?(\d+))?\s*$", re.IGNORECASE)
_SPEC_TAIL_RE = re.compile(r"^[\s_/\-]*(?:спец\D*?)?(\d+)\s*$", re.IGNORECASE)
_SPEC_CONTRACT_RE = re.compile(r"спец.*/\s*(\d+)", re.IGNORECASE)
_LAST4_RE = re.compile(r"(\d{4})(?!\d)")
_BASE_RE = re.compile(r"\s*(\d{4})")


def _compose(head, spec):
    return f"{head} {spec}" if spec else head


def parse_gk_key(value):
    """Ключ из метки/ключа («6066 162сб_5» -> «6066/162сб 5») или None."""
    text = str(value or "").strip()

    m = _GK_RE.search(text)
    if m:
        head = f"{m.group(1)}/{m.group(2)}сб"
        tail = _SPEC_TAIL_RE.match(text[m.end():])
        return _compose(head, tail.group(1) if tail else None)

    m = _BASE_ONLY_RE.match(text)
    if m:
        return _compose(m.group(1), m.group(2))

    return None


def gk_key(value):
    """Ключ ГК; если разобрать не удалось — строка без изменений."""
    text = str(value or "").strip()
    return parse_gk_key(text) or text


def key_from_contract(text):
    """Ключ из строки «Договор/Дата».

    «…06066/162сб/137 от 16.03.2021г.»            -> «6066/162сб»
    «…06066/137 от 16.03.2021г.»                  -> «6066»
    «…0984/81сб/137 от 10.02.2021г. спец…/5»      -> «0984/81сб 5»
    """
    text = str(text or "")
    m = _GK_RE.search(text)
    if m:
        head = f"{m.group(1)}/{m.group(2)}сб"
    else:
        m = _LAST4_RE.search(text)
        if not m:
            return None
        head = m.group(1)

    spec = _SPEC_CONTRACT_RE.search(text)
    return _compose(head, spec.group(1) if spec else None)


def gk_base(key):
    """Первые 4 цифры ключа («6066/162сб 5» -> «6066»)."""
    m = _BASE_RE.match(str(key or ""))
    return m.group(1) if m else str(key or "").strip()
