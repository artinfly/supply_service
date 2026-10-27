"""Нормализация данных из staging-таблиц в рабочие таблицы, отслеживание изменений."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from django.core.management.base import CommandError
from django.db import connection, transaction
from django.utils import timezone

from ..queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    POSTPAYMENT,
    YEARS,
)
from .linking import contract_hash, relink_znp_parents

# --- Константы и маппинги ---


TWO_PLACES = Decimal("0.01")
YEAR_COLS = [f"y{str(y)[2:]}" for y in YEARS]
STATUS_PLACEHOLDERS = ", ".join(["%s"] * len(CONCLUDED))

# Маппинг русских названий месяцев для парсинга дат
MONTH_MAP = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


# --- Утилиты преобразования данных ---


def to_decimal(value):
    """Преобразует значение в Decimal. Возвращает None для пустых/некорректных значений."""
    if value is None:
        return None

    text = str(value).strip()
    if text in {"", "-", "None"}:
        return None

    try:
        cleaned = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def year_flags(god_igk):
    """Возвращает кортеж булевых флагов годов (y25, y26, y27) для значения ГодИГК."""
    try:
        year = int(str(god_igk).strip()[:4])
    except (ValueError, TypeError):
        year = None

    return tuple(year == y for y in YEARS)


def norm(value):
    """Нормализует строку: убирает пробелы, возвращает None для пустых значений."""
    return str(value).strip() if value is not None else None


def plan_month(value):
    """Месяц плановой даты в виде «ГГГГ.ММ».

    Принимает:
        «15.03.2025»            — дата текстом (ДД.ММ.ГГГГ)
        «2025.03»               — уже готовый месяц (ГГГГ.ММ)
        «2025-03-15 00:00:00»   — ячейка Excel с настоящей датой: при импорте
                                  она превращается в такую строку (str(datetime))
    """
    text = norm(value)
    if not text:
        return None

    # Ячейка Excel типа «дата» (раньше такие даты терялись и plan_date был пустым)
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        return f"{text[:4]}.{text[5:7]}"

    parts = text.split(".")

    # Формат ДД.ММ.ГГГГ
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}.{parts[1].zfill(2)}"

    # Формат ГГГГ.ММ
    if len(parts) == 2 and len(parts[0]) == 4:
        return f"{parts[0]}.{parts[1].zfill(2)}"

    return None


def values_equal(a, b):
    """Сравнивает два значения с точностью до 2 знаков после запятой."""
    left = to_decimal(a)
    right = to_decimal(b)

    if left is None and right is None:
        return True

    if left is None or right is None:
        return False

    return left.quantize(TWO_PLACES) == right.quantize(TWO_PLACES)


def status_group(status):
    """Определяет группу статуса: concluded, not_concluded или None."""
    if status in CONCLUDED:
        return "concluded"

    if status in NOT_CONCL:
        return "not_concluded"

    return None


def _indexed_lookup(rows, key_fn, value_fn):
    """Создаёт словарь {ключ + индекс: значение} для обработки дубликатов.

    Если ключ повторяется, добавляется числовой индекс (0, 1, 2, ...).
    """
    counts = defaultdict(int)
    result = {}

    for row in rows:
        base_key = key_fn(row)
        index = counts[base_key]
        counts[base_key] += 1
        result[base_key + (index,)] = value_fn(row)

    return result


def text_ru_date_to_date(value):
    """Парсит дату из формата «15 марта 2021» в date объект."""
    text = norm(value)
    if not text:
        return None

    parts = text.split()
    if len(parts) < 3:
        return None

    day_str, month_str, year_str = parts[:3]
    month = MONTH_MAP.get(month_str.rstrip("."))

    if month is None:
        return None

    day_digits = "".join(ch for ch in day_str if ch.isdigit())
    year_digits = "".join(ch for ch in year_str if ch.isdigit())

    if not day_digits or len(year_digits) < 4:
        return None

    try:
        return date(int(year_digits[:4]), month, int(day_digits))
    except ValueError:
        return None


def dot_date_to_date(value):
    """Парсит дату из форматов «15.03.2021» или «2021-03-15» в date объект."""
    text = norm(value)
    if not text:
        return None

    parts = text.split()
    if not parts:
        return None

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(parts[0], fmt).date()
        except ValueError:
            continue

    return None


def parse_date(value):
    """Парсит дату из различных форматов (точка, дефис, русский текст)."""
    result = dot_date_to_date(value)
    if result:
        return result

    return text_ru_date_to_date(value)


# --- Нормализация договоров ---


class Position(NamedTuple):
    """Позиция договора в том виде, в каком она пишется в igk_stat_data.

    Порядок полей совпадает с колонками INSERT в _write_positions.
    """

    igk: str | None
    c_agent: str | None
    cfo: str | None
    contract: str | None
    status: str | None
    payment_type: str | None
    item: str | None
    order: str | None
    plan: Decimal | None
    fact: Decimal | None
    tolerance: Decimal | None
    stage: str | None
    y25: bool
    y26: bool
    y27: bool
    plan_date: str | None
    c_date: str | None  # год из «ГодИГК» (имя поля историческое)
    contract_sum: Decimal | None
    crc32_hash: int
    remainder: Decimal | None


def _position_key(igk, c_agent, contract, item, order, stage, plan_date) -> tuple:
    """Ключ позиции для сравнения загрузок: ИГК, контрагент, договор, предмет,
    заказ, этап и месяц плана (пустые значения — пустая строка).

    Склейка этих же полей даёт MD5-хеш записи истории (см. queries._HISTORY_JOIN).
    """
    return tuple(
        norm(v) or "" for v in (igk, c_agent, contract, item, order, stage, plan_date)
    )


def _sync_igk_directory(cur) -> None:
    """Справочник ИГК = ИГК из загруженного файла: новые добавляются, пропавшие удаляются."""
    file_igks = """
        SELECT DISTINCT TRIM(igk) FROM staging_excel
        WHERE igk IS NOT NULL AND TRIM(igk) <> ''
    """
    cur.execute(f"INSERT INTO nsi_igk (igk) {file_igks} ON CONFLICT DO NOTHING")
    cur.execute(f"DELETE FROM nsi_igk WHERE igk NOT IN ({file_igks})")


def _read_contract_staging(cur) -> list[Position]:
    """Позиции из staging_excel (только «Аванс» и «Постоплата»), приведённые к типам.

    Исключения:
        CommandError: в файле нет ни одной такой строки. Пустой файл не должен
            стирать загруженные договоры: ошибка откатывает всю загрузку.
    """
    cur.execute(
        """
        SELECT igk, kontragent, cfo, dogovor, sostoyanie,
               tip_platezha, predmet, zakaz, plan, fakt,
               tol, etap_grafika, dataplan, summa_dogovora, god_igk,
               ostatok
        FROM staging_excel
        WHERE tip_platezha IN (%s, %s)
        """,
        [ADVANCE, POSTPAYMENT],
    )
    rows = cur.fetchall()
    if not rows:
        raise CommandError(
            f"В файле нет строк с типом платежа «{ADVANCE}» или «{POSTPAYMENT}» — "
            "данные не изменены. Проверьте, что выбран нужный тип файла."
        )

    positions = []
    for (
        igk,
        agent,
        cfo,
        contract,
        status,
        payment,
        item,
        order,
        plan,
        fact,
        tolerance,
        stage,
        plan_date,
        contract_sum,
        god_igk,
        remainder,
    ) in rows:
        positions.append(
            Position(
                igk=norm(igk),
                c_agent=norm(agent),
                cfo=norm(cfo),
                contract=norm(contract),
                status=norm(status),
                payment_type=norm(payment) or None,
                item=norm(item),
                order=norm(order),
                plan=to_decimal(plan),
                fact=to_decimal(fact),
                tolerance=to_decimal(tolerance),
                stage=norm(stage),
                y25=year_flags(god_igk)[0],
                y26=year_flags(god_igk)[1],
                y27=year_flags(god_igk)[2],
                plan_date=plan_month(plan_date),
                c_date=norm(god_igk),
                contract_sum=to_decimal(contract_sum),
                crc32_hash=contract_hash(
                    norm(igk), norm(agent), norm(contract), norm(stage)
                ),
                remainder=to_decimal(remainder),
            )
        )
    return positions


def _previous_positions(cur) -> dict:
    """Позиции прошлой загрузки: {ключ + № повтора: (статус, план, факт, сумма договора)}."""
    cur.execute("""
        SELECT igk, c_agent, contract, item, "order", stage, plan_date,
               status, plan, fact, contract_sum
        FROM igk_stat_data
        ORDER BY pp_id
    """)
    return _indexed_lookup(
        cur.fetchall(),
        key_fn=lambda r: _position_key(*r[:7]),
        value_fn=lambda r: (r[7], r[8], r[9], r[10]),
    )


def _appeared_rows(old: dict, new: dict, today) -> list[tuple]:
    """Позиции, которые появились или перешли между «заключён» и «не заключён».

    При самой первой загрузке (прошлой нет) журнал не заполняется.
    """
    if not old:
        return []
    rows = []
    for key, pos in new.items():
        kind = status_group(pos.status)
        if kind is None:
            continue
        previous = old.get(key)
        if previous is None:
            reason = "новая позиция"
        elif status_group(previous[0]) == kind:
            continue
        else:
            reason = "смена статуса"
        rows.append(
            (
                today,
                kind,
                reason,
                pos.igk,
                pos.cfo,
                pos.c_agent,
                pos.contract,
                pos.item,
                pos.order,
                pos.stage,
                pos.plan_date,
                pos.status,
                pos.plan,
                pos.contract_sum,
            )
        )
    return rows


def _history_rows(old: dict, new: dict, today) -> list[tuple]:
    """Изменения статуса, плана, факта и суммы договора у позиций, бывших в прошлой загрузке."""
    rows = []
    for key, pos in new.items():
        if key not in old:
            continue
        old_status, old_plan, old_fact, old_sum = old[key]
        status_changed = old_status != pos.status
        plan_changed = not values_equal(old_plan, pos.plan)
        fact_changed = not values_equal(old_fact, pos.fact)
        sum_changed = not values_equal(old_sum, pos.contract_sum)
        if not (status_changed or plan_changed or fact_changed or sum_changed):
            continue
        rows.append(
            (
                "".join(key[:-1]),  # склейка ключа без № повтора -> MD5 в SQL
                old_status if status_changed else None,
                pos.status if status_changed else None,
                today if status_changed else None,
                today if status_changed else None,
                old_plan if plan_changed else None,
                pos.plan if plan_changed else None,
                old_fact if fact_changed else None,
                pos.fact if fact_changed else None,
                today if plan_changed else None,
                today if fact_changed else None,
                old_sum,
                pos.contract_sum,
            )
        )
    return rows


def _write_positions(cur, positions: list[Position]) -> None:
    """Перезаписывает рабочую таблицу договоров целиком."""
    cur.execute("TRUNCATE igk_stat_data RESTART IDENTITY")
    cur.executemany(
        """
        INSERT INTO igk_stat_data
            (igk, c_agent, cfo, contract, status, payment_type,
             item, "order", plan, fact, tolerance, stage,
             y25, y26, y27, plan_date, c_date, contract_sum,
             crc32_hash, remainder)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        positions,
    )


def _save_snapshots(cur, today) -> None:
    """Снимок числа заключённых договоров по ИГК/ЦФО/году — для дельты в выгрузке КДР."""
    cur.execute("DELETE FROM contract_counts_snapshot WHERE upload_date = %s", [today])
    for year_col in YEAR_COLS:
        cur.execute(
            f"""
            INSERT INTO contract_counts_snapshot
                (upload_date, igk, cfo, year_col, concluded_count)
            SELECT %s, RIGHT(igk, 4), cfo, %s, COUNT(DISTINCT contract)
            FROM igk_stat_data
            WHERE {year_col}=TRUE
              AND status IN ({STATUS_PLACEHOLDERS})
              AND contract IS NOT NULL AND TRIM(contract) != ''
              AND igk IS NOT NULL AND TRIM(igk) != ''
              AND cfo IS NOT NULL AND TRIM(cfo) != ''
            GROUP BY RIGHT(igk, 4), cfo
            """,
            [today, year_col, *CONCLUDED],
        )


def normalize_contracts():
    """Переносит договоры из staging_excel в igk_stat_data с учётом прошлой загрузки.

    Шаги: справочник ИГК → позиции из файла → сравнение с прошлой загрузкой
    (журнал появившихся и история изменений) → перезапись рабочей таблицы →
    снимки для КДР → перепривязка заявок ФЗД. Всё в одной транзакции.

    Returns:
        str: отчёт о количестве обработанных строк и записанных изменений.
    """
    today = timezone.localdate()
    with transaction.atomic(), connection.cursor() as cur:
        _sync_igk_directory(cur)
        positions = _read_contract_staging(cur)

        old = _previous_positions(cur)
        new = _indexed_lookup(
            positions,
            key_fn=lambda p: _position_key(
                p.igk, p.c_agent, p.contract, p.item, p.order, p.stage, p.plan_date
            ),
            value_fn=lambda p: p,
        )

        appeared = _appeared_rows(old, new, today)
        if appeared:
            cur.executemany(
                """
                INSERT INTO contracts_appeared
                (upload_date, kind, reason, igk, cfo, c_agent, contract,
                 item, order_num, stage, plan_date, status, plan, contract_sum)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                appeared,
            )

        history = _history_rows(old, new, today)
        if history:
            cur.executemany(
                """
                INSERT INTO contracts_history
                    (hash, old_status, new_status, update_date, upload_date,
                     old_plan, new_plan, old_fact, new_fact,
                     plan_changed_date, fact_changed_date,
                     old_contract_sum, new_contract_sum)
                VALUES (digest(%s, 'md5'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s)
                """,
                history,
            )

        _write_positions(cur, positions)
        _save_snapshots(cur, today)
        relink_znp_parents()

    return f"обработано строк: {len(positions)}, изменений записано: {len(history)}"


# --- Нормализация заявок ФЗД ---


def normalize_znp():
    """Нормализует данные заявок ФЗД из staging_znp_excel в znp_data.

    Returns:
        str: отчёт о количестве обработанных заявок и без совпадений
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT crc32_hash, plan_doc, payment_purpose,
                   plan_payment_date, fact_payment_date,
                   plan_sum, fact_sum, stage, znp_igk,
                   znp_payment_type, znp_status, znp_date
            FROM staging_znp_excel
        """)
        staging_rows = cur.fetchall()
        if not staging_rows:
            raise CommandError(
                "В файле нет ни одной заявки с номером планового документа — "
                "данные не изменены. Проверьте, что выбран нужный тип файла."
            )

        new_data = []

        for r in staging_rows:
            new_data.append(
                (
                    None,  # parent_id (заполняется позже)
                    norm(r[1]),  # plan_doc
                    norm(r[2]),  # payment_purpose
                    parse_date(r[3]),  # plan_payment_date
                    parse_date(r[4]),  # fact_payment_date
                    to_decimal(r[5]),  # plan_sum
                    to_decimal(r[6]),  # fact_sum
                    r[0],  # crc32_hash
                    norm(r[7]),  # stage
                    norm(r[8]),  # znp_igk
                    norm(r[9]),  # znp_payment_type
                    norm(r[10]),  # znp_status
                    parse_date(r[11]),  # znp_date
                )
            )

        cur.execute("TRUNCATE znp_data RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data
                (parent_id, plan_doc, payment_purpose,
                plan_payment_date, fact_payment_date, plan_sum,
                fact_sum, crc32_hash, stage, znp_igk, znp_payment_type,
                znp_status, znp_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            new_data,
        )

        # Перепривязываем заявки к позициям договоров
        relink_znp_parents()

        cur.execute("SELECT COUNT(*) FROM znp_data WHERE parent_id IS NULL")
        unmatched_count = cur.fetchone()[0]

    return (
        f"обработано заявок: {len(new_data)}, "
        f"без совпадения с договором: {unmatched_count}"
    )


# --- Нормализация заявок SAP ---


def normalize_znp_sap():
    """Нормализует данные заявок SAP из staging_znp_sap_excel в znp_data_sap.

    Returns:
        str: отчёт о количестве обработанных заявок и без ИГК
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT igk, cfo, c_agent, reg_num, items, vv_sum,
                   bank_name, stage_e, stage_f, stage_c, payment_possible,
                   normalize_doc_num, created_date
            FROM staging_znp_sap_excel
            WHERE c_type = 'ГОЗ'
        """)
        staging_rows = cur.fetchall()
        # Колонки SAP берутся по номерам, без проверки шапки: если выбрать не тот
        # файл, строк «ГОЗ» не найдётся — тогда не очищаем загруженные заявки
        if not staging_rows:
            raise CommandError(
                "В файле нет заявок с типом «ГОЗ» (столбец I) — данные не изменены. "
                "Проверьте, что выбран файл выгрузки ЗнП (SAP)."
            )

        new_data = []
        no_igk_count = 0

        for r in staging_rows:
            if r[0] is None:
                no_igk_count += 1
            new_data.append(r)

        cur.execute("TRUNCATE znp_data_sap RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data_sap
                (igk, cfo, c_agent, reg_num, items, vv_sum,
                 bank_name, stage_e, stage_f, stage_c, payment_possible,
                 normalize_doc_num, created_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
