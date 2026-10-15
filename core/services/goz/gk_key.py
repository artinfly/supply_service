"""Единый формат ключа ГК в справочнике и в отчёте.

ИГК — последние 4 цифры длинного номера. Ключи:

    Имя файла в архиве (после №…)        Договор/Дата в справочнике                    Ключ
    1. …1493                             …1493/137 от …                                1493
    2. …6766_12                          …6766/12 от …                                 6766 12
    3. …0087_334сб_137                   …0087/334сб/137 от …                          0087/334сб
    4. …0276_481сб_137_138               …0276/481сб/137 от …, спец…/138               0276/481сб 138
    5. …4238_3_3_6_30-2014-ДГОЗ          —                                             4238_3_3_6_30-2014-ДГОЗ
    6. …0998_439сб_19                    …0998/439сб/19 от …                           0998/439сб 19

Число после пробела — спецификация. «137» — номер договора: в ключ не пишется,
если стоит сразу после «сб» (…_334сб_137) или после ИГК в договоре (…1493/137 от …).
Но спецификация тоже может иметь номер 137: в имени файла без «сб» (…000262_137)
и в договоре после слова «спец» (…/255сб/137 от …, спец…./137) — это ключ «0262 137»
(файл) и «0262/255сб 137» (справочник), они находятся друг по другу.
«1493», «1493 5», «1493/34сб», «1493/34сб 5» — разные ГК.
"""

import re

# Номер договора «137» в ключ не попадает никогда: ни как сб, ни как спец
CONTRACT_NO = "137"

# Отдельное «137» в хвосте: «_137», «/137», « 137» (но не «1370» и не «2137»)
_CONTRACT_NO_TOKEN_RE = re.compile(rf"(?<=[_/\s]){CONTRACT_NO}(?=[_/\s.]|$)")

_SB = r"(\d+)\s*[сc]б"

# Уже готовый ключ: «1493», «1493 5», «1493/34сб», «1493/34сб 5»
_KEY_RE = re.compile(rf"^(\d{{4}})(?:/{_SB})?(?: (\d+))?$", re.IGNORECASE)

# Последние 4 цифры длинного номера = ИГК
_LAST4_RE = re.compile(r"(\d{4})(?!\d)")

# Хвост из имени файла: «_334сб», «_334сб_137», «_481сб_137_138», «_439сб_19»
# Перед номером сб иногда стоят ещё числа: «_624_379сб_137» — берём то, что
# написано вплотную к «сб» (379), остальные отбрасываем.
_FILE_SB_RE = re.compile(
    rf"^(?:[_/\s]+\d+)*?[_/\s]+{_SB}(?:[_/\s]+(\d+))?(?:[_/\s]+(\d+))?$", re.IGNORECASE
)

# Хвост из имени файла без сб: «_12» -> спец
_FILE_SPEC_RE = re.compile(r"^[_/\s]+(\d+)$")

# Договор: «/481сб/137 от …», «/439сб/19 от …», «/12 от …»
_CONTRACT_SB_RE = re.compile(rf"^/{_SB}(?:/(\d+))?", re.IGNORECASE)
_CONTRACT_NO_RE = re.compile(r"^/(\d+)")

# Спец в договоре: «спец…/138», «спец. …/175», «Спец…205»
_SPEC_WORD_RE = re.compile(r"спец\D*?(\d+)", re.IGNORECASE)


def _compose(igk, sb=None, spec=None):
    key = f"{igk}/{sb}сб" if sb else igk
    return f"{key} {spec}" if spec else key


def _drop_contract_no(rest):
    """Убирает из хвоста отдельное «137» и лишние разделители."""
    rest = _CONTRACT_NO_TOKEN_RE.sub("", rest)
    rest = re.sub(r"[_/]{2,}", "_", rest)
    return re.sub(r"[_/\s]+$", "", rest)


def _spec_after_sb(numbers):
    """Числа после сб -> спец («137» отбрасывается).

    []            -> нет спеца
    ["137"]       -> нет спеца
    ["19"]        -> спец 19
    ["137", "7"]  -> спец 7
    """
    numbers = [n for n in numbers if n and n != CONTRACT_NO]
    return numbers[-1] if numbers else None


def key_from_contract(text):
    """Ключ из строки «Договор/Дата» справочника (см. таблицу в начале файла)."""
    text = str(text or "")
    m = _LAST4_RE.search(text)
    if not m:
        return None
    igk, rest = m.group(1), text[m.end():]

    # Число после слова «спец» — всегда спецификация, даже если это 137
    spec_word = _SPEC_WORD_RE.search(text)
    spec_word = spec_word.group(1) if spec_word else None

    sb_m = _CONTRACT_SB_RE.match(rest)
    if sb_m:
        spec = spec_word or _spec_after_sb([sb_m.group(2)])
        return _compose(igk, sb_m.group(1), spec)

    no_m = _CONTRACT_NO_RE.match(rest)
    spec = spec_word or (no_m.group(1) if no_m and no_m.group(1) != CONTRACT_NO else None)
    return _compose(igk, spec=spec)


def _key_from_label(text):
    """Ключ из метки файла «ИГК_хвост» (ИГК — первые 4 цифры)."""
    m = re.match(r"^\s*(\d{4})(.*)$", text)
    if not m:
        return None
    igk, raw = m.group(1), m.group(2)
    rest = re.sub(r"[_/\s]+$", "", raw.rstrip())

    if not rest:
        return igk  # 1. просто ГК

    sb_m = _FILE_SB_RE.match(rest)
    if sb_m:  # 3, 4, 6: «137» после сб — номер договора, отбрасывается в _spec_after_sb
        return _compose(igk, sb_m.group(1), _spec_after_sb([sb_m.group(2), sb_m.group(3)]))

    spec_m = _FILE_SPEC_RE.match(rest)
    if spec_m:  # 2. ГК_число — спец (в том числе «_137»: без сб это номер спецификации)
        return _compose(igk, spec=spec_m.group(1))

    # 5. «_3_3_6_30-2014-ДГОЗ» и прочие длинные — целиком, через «_»
    rest = _drop_contract_no(raw.rstrip())
    return f"{igk}_{rest.lstrip('_/ ')}"


def parse_gk_key(value):
    """Нормализует метку ГК (ключ, имя файла или строку договора) или None."""
    text = str(value or "").strip()
    if not text:
        return None

    key_m = _KEY_RE.match(text)
    if key_m:  # уже готовый ключ — берём как есть (спецификация может быть и 137)
        igk, sb, spec = key_m.groups()
        return _compose(igk, sb, spec)

    if re.search(r"\sот\s|спец", text, re.IGNORECASE):
        return key_from_contract(text)

    return _key_from_label(text)


def gk_key(value):
    """Ключ ГК; если разобрать не удалось — строка без изменений."""
    text = str(value or "").strip()
    return parse_gk_key(text) or text
