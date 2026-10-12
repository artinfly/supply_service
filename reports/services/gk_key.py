"""Единый формат ключа ГК в справочнике и в отчёте: «игк/111сб».

игк — последние 4 цифры номера ИГК, 111сб — номер сборочного контракта.
Один и тот же ключ получается из:
  «6066 162сб», «6066_162сб», «6066/162сб»
  «2020181812122424242406066/162сб/137 от 16.03.2021г.»
"""

import re

_GK_RE = re.compile(r"(\d{4})(?!\d)\s*[/_\s\-]*\s*(\d+)\s*[сc]б", re.IGNORECASE)
_BASE_RE = re.compile(r"\s*(\d{4})")


def parse_gk_key(value):
    """Ключ вида «6066/162сб» или None, если сб в строке не найден."""
    m = _GK_RE.search(str(value or ""))
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}сб"


def gk_key(value):
    """Ключ ГК; если сб не найден — строка без изменений (старый формат)."""
    text = str(value or "").strip()
    return parse_gk_key(text) or text


def gk_base(key):
    """Первые 4 цифры ключа («6066/162сб» -> «6066»)."""
    m = _BASE_RE.match(str(key or ""))
    return m.group(1) if m else str(key or "").strip()
