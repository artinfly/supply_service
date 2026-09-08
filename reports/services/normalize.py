"""
Модуль нормализации данных из staging-таблиц в рабочие таблицы.

Отвечает за:
- Конвертацию сырых данных из staging-таблиц в правильные типы
- Вычисление производных полей (crc32_hash, флаги годов, остатки)
- Запись истории изменений договоров (статус, план, факт, сумма)
- Фиксацию появившихся договоров (новые или изменившие статус)
- Создание снимков количества заключённых договоров для графиков
- Привязку заявок ФЗД к позициям договоров через crc32_hash

Логика работы:
1. Данные читаются из staging-таблиц (где всё хранится как текст)
2. Выполняется конвертация типов и вычисление производных полей
3. Сравниваются с предыдущими данными для выявления изменений
4. Записывается история изменений и журнал появившихся договоров
5. Рабочие таблицы полностью перезаписываются новыми данными
6. Создаются снимки для графиков динамики
7. Привязываются заявки ФЗД к позициям договоров

Все операции выполняются в одной транзакции. При ошибке база остаётся прежней.
"""

from collections import defaultdict
from datetime import date, datetime

from django.db import connection, transaction
from django.utils import timezone

from reports.services.linking import contract_hash, relink_znp_parents
from reports.services.queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    POSTPAYMENT,
    YEARS,
)

# ============================================================================
# Вспомогательные функции конвертации
# ============================================================================


def to_float(val):
    """
    Конвертирует строковое значение в float с обработкой ошибок.

    Удаляет неразрывные пробелы (\xa0), обычные пробелы и заменяет запятые на точки.
    Возвращает None для пустых строк, "-", "None" и некорректных значений.

    Используется для конвертации плановых и фактических сумм из staging-таблиц.
    """
    if val is None or str(val).strip() in ("", "-", "None"):
        return None
    try:
        return float(str(val).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def year_flags(god_igk):
    """
    Определяет флаги годов для позиции договора на основе колонки "ГодИГК".

    Извлекает первые 4 символа (год) и сравнивает с каждым годом из YEARS.
    Возвращает кортеж булевых значений: (y25, y26, y27).

    Пример: если ГодИГК="2026...", вернёт (False, True, False).
    """
    try:
        y = int(str(god_igk).strip()[:4])
    except Exception:
        y = None
    return tuple(y == year for year in YEARS)


def norm(val):
    """
    Нормализует строковое значение: убирает пробелы по краям, None превращает в None.

    Используется для единообразной обработки текстовых полей перед записью в БД.
    """
    return str(val).strip() if val is not None else None


def plan_month(val):
    """
    Извлекает год и месяц из плановой даты в формате "YYYY.MM" или "MM.YYYY".

    Поддерживает два формата:
    - "2026.05" -> "2026.05"
    - "05.2026" -> "2026.05"

    Возвращает None если формат не распознан.
    """
    text = norm(val)
    if not text:
        return None
    parts = text.split(".")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}.{parts[1].zfill(2)}"
    if len(parts) == 2 and len(parts[0]) == 4:
        return f"{parts[0]}.{parts[1].zfill(2)}"
    return None


def floats_equal(a, b):
    """
    Сравнивает два float значения с точностью до 2 знаков после запятой.

    Используется для определения, изменились ли плановые/фактические суммы
    при сравнении текущей загрузки с предыдущей.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(float(a), 2) == round(float(b), 2)


# ============================================================================
# Константы и маппинги
# ============================================================================

# SQL-строка со списком статусов заключённых договоров для использования в IN (...)
CONCLUDED_SQL = ", ".join(f"'{s}'" for s in CONCLUDED)

# Маппинг имени колонки-флага года на значение года: [("y25", 2025), ("y26", 2026), ...]
YEAR_MAP = [(f"y{str(y)[2:]}", y) for y in YEARS]


def status_group(status):
    """
    Определяет группу статуса договора для журнала появившихся договоров.

    Возвращает:
    - "concluded" для статусов из CONCLUDED
    - "not_concluded" для статусов из NOT_CONCL
    - None для остальных статусов (расторгнутые не фиксируются)
    """
    if status in CONCLUDED:
        return "concluded"
    if status in NOT_CONCL:
        return "not_concluded"
    return None


def _indexed_lookup(rows, key_fn, value_fn):
    """
    Строит индексированный словарь для быстрого поиска строк по составному ключу.

    Если в данных есть дубликаты по ключу, добавляет дополнительный индекс (0, 1, 2...).
    Это позволяет корректно обрабатывать случаи, когда одна и та же позиция договора
    встречается несколько раз с одинаковыми ключевыми полями.

    Параметры:
    - rows: список кортежей (строки из БД или списка new_data)
    - key_fn: функция, извлекающая ключ из строки (кортеж полей)
    - value_fn: функция, извлекающая значение из строки

    Возвращает словарь: {ключ + (индекс,): значение}
    """
    counts = defaultdict(int)
    result = {}
    for r in rows:
        base_key = key_fn(r)
        idx = counts[base_key]
        counts[base_key] += 1
        result[base_key + (idx,)] = value_fn(r)
    return result


# Маппинг названий месяцев на русском языке на номера месяцев
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


# ============================================================================
# Функции парсинга дат
# ============================================================================


def text_ru_date_to_date(val: str):
    """
    Парсит дату в формате "ДД месяц ГГГГ" (например, "15 сентября 2026").

    Используется для плановых и фактических дат оплаты заявок ФЗД.
    Возвращает объект date или None если формат не распознан.
    """
    if val is None:
        return None

    parts = val.split()
    if len(parts) != 3:
        return None

    day_str, month_str, year_str = parts
    month = MONTH_MAP.get(month_str)
    if month is None:
        return None

    try:
        return date(int(year_str), month, int(day_str))
    except ValueError:
        return None


def dot_date_to_date(val):
    """
    Парсит дату в формате "ДД.ММ.ГГГГ" или "ГГГГ-ММ-ДД".

    Используется для дат заявок ФЗД.
    Возвращает объект date или None если формат не распознан.
    """
    if val is None:
        return None
    parts = str(val).strip().split()
    if not parts:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(parts[0], fmt).date()
        except ValueError:
            continue
    return None


# ============================================================================
# Основная функция нормализации договоров
# ============================================================================


def normalize_contracts():
    """
    Нормализует данные договоров из staging_excel в igk_stat_data.

    Выполняет следующие шаги в одной транзакции:

    1. Обновляет справочник ИГК (nsi_igk) уникальными значениями из файла

    2. Читает строки из staging_excel с типами платежа "Аванс" или "Постоплата"
       и конвертирует их в кортежи для вставки в igk_stat_data:
       - Текстовые поля нормализуются через norm()
       - Числовые поля конвертируются через to_float()
       - Вычисляются флаги годов через year_flags()
       - Вычисляется crc32_hash для привязки заявок ФЗД

    3. Загружает предыдущие данные из igk_stat_data и строит индексированный словарь
       для сравнения с новыми данными

    4. Сравнивает новые данные с предыдущими и выявляет:
       - Появившиеся договоры (новые позиции или изменившие статус)
       - Изменения статуса, плана, факта и суммы договора

    5. Записывает в contracts_appeared журнал появившихся договоров

    6. Записывает в contracts_history историю изменений через MD5-хеш позиции

    7. Полностью перезаписывает igk_stat_data новыми данными

    8. Создаёт снимки contract_counts_snapshot для каждого года:
       количество заключённых договоров по комбинации (ИГК, ЦФО, год)

    9. Вызывает relink_znp_parents() для привязки заявок ФЗД к позициям договоров

    Возвращает строку с количеством обработанных строк и записанных изменений.
    """
    with transaction.atomic(), connection.cursor() as cur:
        # Шаг 1: Обновление справочника ИГК
        cur.execute("""
            INSERT INTO nsi_igk (igk)
            SELECT DISTINCT TRIM(igk) FROM staging_excel
            WHERE igk IS NOT NULL AND TRIM(igk) <> ''
            ON CONFLICT DO NOTHING
        """)

        # Шаг 2: Чтение и конвертация данных из staging
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
        staging_rows = cur.fetchall()

        new_data = []
        for r in staging_rows:
            y25, y26, y27 = year_flags(r[14])
            new_data.append(
                (
                    norm(r[0]),  # igk
                    norm(r[1]),  # c_agent
                    norm(r[2]),  # cfo
                    norm(r[3]),  # contract
                    norm(r[4]),  # status
                    norm(r[5]) or None,  # payment_type
                    norm(r[6]),  # item
                    norm(r[7]),  # order
                    to_float(r[8]),  # plan
                    to_float(r[9]),  # fact
                    to_float(r[10]),  # tolerance
                    norm(r[11]),  # stage
                    y25,  # y25
                    y26,  # y26
                    y27,  # y27
                    plan_month(r[12]),  # plan_date
                    norm(r[14]),  # c_date (god_igk используется как c_date)
                    to_float(r[13]),  # contract_sum
                    contract_hash(
                        norm(r[0]), norm(r[1]), norm(r[3]), norm(r[11])
                    ),  # crc32_hash
                    to_float(r[15]),  # remainder
                )
            )

        # Шаг 3: Загрузка предыдущих данных для сравнения
        cur.execute("""
            SELECT igk, c_agent, contract, item, "order", stage, plan_date,
                   status, plan, fact, contract_sum
            FROM igk_stat_data
            ORDER BY pp_id
        """)
        old_lookup = _indexed_lookup(
            cur.fetchall(),
            key_fn=lambda r: (
                norm(r[0]) or "",  # igk
                norm(r[1]) or "",  # c_agent
                norm(r[2]) or "",  # contract
                norm(r[3]) or "",  # item
                norm(r[4]) or "",  # order
                norm(r[5]) or "",  # stage
                norm(r[6]) or "",  # plan_date
            ),
            value_fn=lambda r: (
                r[7],
                r[8],
                r[9],
                r[10],
            ),  # status, plan, fact, contract_sum
        )

        new_lookup = _indexed_lookup(
            new_data,
            key_fn=lambda r: (
                r[0] or "",  # igk
                r[1] or "",  # c_agent
                r[3] or "",  # contract
                r[6] or "",  # item
                r[7] or "",  # order
                r[11] or "",  # stage
                r[15] or "",  # remainder (используется как часть ключа)
            ),
            value_fn=lambda r: r,
        )

        # Шаг 4-5: Выявление и запись появившихся договоров
        today = timezone.localdate()
        appeared = []
        if old_lookup:
            for key, row in new_lookup.items():
                kind = status_group(row[4])  # status
                if kind is None:
                    continue
                old_row = old_lookup.get(key)
                if old_row is None:
                    reason = "новая позиция"
                elif status_group(old_row[0]) == kind:
                    continue
                else:
                    reason = "смена статуса"
                appeared.append(
                    (
                        today,  # upload_date
                        kind,  # kind
                        reason,  # reason
                        row[0],  # igk
                        row[2],  # cfo
                        row[1],  # c_agent
                        row[3],  # contract
                        row[6],  # item
                        row[7],  # order_num
                        row[11],  # stage
                        row[15],  # plan_date
                        row[4],  # status
                        row[8],  # plan
                        row[17],  # contract_sum
                    )
                )
        if appeared:
            cur.executemany(
                """
                INSERT INTO contracts_appeared
                (upload_date, kind, reason, igk, cfo, c_agent, contract, item, order_num, stage, plan_date, status, plan, contract_sum)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
                appeared,
            )

        # Шаг 6: Выявление и запись истории изменений
        history = []
        for key, new_row in new_lookup.items():
            if key not in old_lookup:
                continue
            old_vals = old_lookup[key]

            old_status, old_plan, old_fact, old_sum = old_vals
            new_status, new_plan, new_fact, new_sum = (
                new_row[4],  # status
                new_row[8],  # plan
                new_row[9],  # fact
                new_row[17],  # contract_sum
            )

            status_changed = old_status != new_status
            plan_changed = not floats_equal(old_plan, new_plan)
            fact_changed = not floats_equal(old_fact, new_fact)
            sum_changed = not floats_equal(old_sum, new_sum)

            if not (status_changed or plan_changed or fact_changed or sum_changed):
                continue

            history.append(
                (
                    "".join(key[:-1]),  # hash (конкатенация ключевых полей)
                    old_status if status_changed else None,
                    new_status if status_changed else None,
                    today if status_changed else None,  # update_date
                    today if status_changed else None,  # upload_date
                    old_plan if plan_changed else None,
                    new_plan if plan_changed else None,
                    old_fact if fact_changed else None,
                    new_fact if fact_changed else None,
                    today if plan_changed else None,  # plan_changed_date
                    today if fact_changed else None,  # fact_changed_date
                    old_sum,
                    new_sum,
                )
            )

        if history:
            cur.executemany(
                """
                INSERT INTO contracts_history
                    (hash, old_status, new_status,
                    update_date, upload_date,
                    old_plan, new_plan,
                    old_fact, new_fact,
                    plan_changed_date, fact_changed_date,
                    old_contract_sum, new_contract_sum)
                VALUES (digest(%s, 'md5'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s)
            """,
                history,
            )

        # Шаг 7: Полная перезапись igk_stat_data
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
            new_data,
        )

        # Шаг 8: Создание снимков для графиков динамики
        cur.execute(
            "DELETE FROM contract_counts_snapshot WHERE upload_date = %s", [today]
        )
        for year_col, year_val in YEAR_MAP:
            cur.execute(
                f"""
                INSERT INTO contract_counts_snapshot (upload_date, igk, cfo, year_col, concluded_count)
                SELECT
                    %s,
                    RIGHT(igk, 4),
                    cfo,
                    %s,
                    COUNT(DISTINCT contract)
                FROM igk_stat_data
                WHERE {year_col}=TRUE
                  AND status IN ({CONCLUDED_SQL})
                  AND contract IS NOT NULL AND TRIM(contract) != ''
                  AND igk IS NOT NULL AND TRIM(igk) != ''
                  AND cfo IS NOT NULL AND TRIM(cfo) != ''
                GROUP BY RIGHT(igk, 4), cfo
            """,
                [today, year_col],
            )

        # Шаг 9: Привязка заявок ФЗД к позициям договоров
        relink_znp_parents()

    return f"обработано строк: {len(new_data)}, изменений записано: {len(history)}"


# ============================================================================
# Нормализация заявок ФЗД
# ============================================================================


def normalize_znp():
    """
    Нормализует данные заявок ФЗД из staging_znp_excel в znp_data.

    Выполняет следующие шаги в одной транзакции:

    1. Читает все строки из staging_znp_excel

    2. Конвертирует данные:
       - Текстовые поля нормализуются через norm()
       - Даты парсятся через text_ru_date_to_date() и dot_date_to_date()
       - Суммы конвертируются через to_float()
       - parent_id устанавливается в NULL (привязка выполнится позже)

    3. Полностью перезаписывает znp_data новыми данными

    4. Вызывает relink_znp_parents() для массовой привязки заявок к позициям
       договоров через crc32_hash. Это гораздо быстрее, чем коррелированный
       подзапрос для каждой строки (O(N) вместо O(N*M)).

    Считает количество заявок без привязки к договору для отчёта.

    Возвращает строку с количеством обработанных заявок и непривязанных заявок.
    """
    with transaction.atomic(), connection.cursor() as cur:
        # Шаг 1-2: Чтение и конвертация данных
        cur.execute("""
            SELECT
                crc32_hash,
                plan_doc,
                payment_purpose,
                plan_payment_date,
                fact_payment_date,
                plan_sum,
                fact_sum,
                stage,
                znp_igk,
                znp_payment_type,
                znp_status,
                znp_date
            FROM staging_znp_excel
        """)
        staging_rows = cur.fetchall()

        new_data = []
        unmatched_count = 0
        for r in staging_rows:
            # parent_id = NULL, привязка выполнится через relink_znp_parents()
            new_data.append(
                (
                    None,  # parent_id (NULL)
                    norm(r[1]),  # plan_doc
                    norm(r[2]),  # payment_purpose
                    text_ru_date_to_date(norm(r[3])),  # plan_payment_date
                    text_ru_date_to_date(norm(r[4])),  # fact_payment_date
                    to_float(r[5]),  # plan_sum
                    to_float(r[6]),  # fact_sum
                    r[0],  # crc32_hash
                    norm(r[7]),  # stage
                    norm(r[8]),  # znp_igk
                    norm(r[9]),  # znp_payment_type
                    norm(r[10]),  # znp_status
                    dot_date_to_date(r[11]),  # znp_date
                )
            )

        # Шаг 3: Полная перезапись znp_data
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

        # Шаг 4: Массовая привязка заявок к позициям договоров
        relink_znp_parents()

        # Подсчёт непривязанных заявок для отчёта
        cur.execute("SELECT COUNT(*) FROM znp_data WHERE parent_id IS NULL")
        unmatched_count = cur.fetchone()[0]

    return f"обработано заявок: {len(new_data)}, без совпадения с договором: {unmatched_count}"


# ============================================================================
# Нормализация заявок SAP
# ============================================================================


def normalize_znp_sap():
    """
    Нормализует данные заявок SAP из staging_znp_sap_excel в znp_data_sap.

    Выполняет следующие шаги в одной транзакции:

    1. Читает строки из staging_znp_sap_excel с фильтром c_type = 'ГОЗ'
       (только заявки государственного оборонного заказа)

    2. Конвертирует данные без изменений типов (все поля уже в правильном формате)

    3. Полностью перезаписывает znp_data_sap новыми данными

    Считает количество заявок без ИГК для отчёта.

    Возвращает строку с количеством обработанных заявок и заявок без ИГК.
    """
    with transaction.atomic(), connection.cursor() as cur:
        # Шаг 1: Чтение данных с фильтром по типу
        cur.execute("""
            SELECT
                igk,
                cfo,
                c_agent,
                reg_num,
                items,
                vv_sum,
                bank_name,
                stage_e,
                stage_f,
                payment_possible,
                init_payment_date,
                normalize_doc_num
            FROM staging_znp_sap_excel szse
            WHERE c_type = 'ГОЗ'
        """)
        staging_rows = cur.fetchall()

        # Шаг 2: Подготовка данных для вставки
        new_data = []
        no_igk_count = 0
        for r in staging_rows:
            if r[0] is None:
                no_igk_count += 1
            new_data.append(
                (
                    r[0],  # igk
                    r[1],  # cfo
                    r[2],  # c_agent
                    r[3],  # reg_num
                    r[4],  # items
                    r[5],  # vv_sum
                    r[6],  # bank_name
                    r[7],  # stage_e
                    r[8],  # stage_f
                    r[9],  # payment_possible
                    r[10],  # init_payment_date
                    r[11],  # normalize_doc_num
                )
            )

        # Шаг 3: Полная перезапись znp_data_sap
        cur.execute("TRUNCATE znp_data_sap RESTART IDENTITY")
        cur.executemany(
            """
            INSERT INTO znp_data_sap
                (igk, cfo, c_agent, reg_num,
                items, vv_sum, bank_name, stage_e, 
                stage_f, payment_possible, init_payment_date, normalize_doc_num
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
            new_data,
        )

    return f"обработано заявок: {len(new_data)}, без ИГК: {no_igk_count}"
