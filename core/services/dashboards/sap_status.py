"""Логика определения статусов заявок SAP.

Важно: карточки дашборда используют полные условия из `sap_status_conditions()`,
поэтому одна заявка может попадать в несколько карточек одновременно.
Однако колонка «Этап» в реестре и график используют единый статус из
`sap_status_expr()` (ORM) или `sap_status_sql()` (raw SQL), где статусы
вычисляются строго по приоритету. Из-за этого суммы в карточках и в реестре
могут отличаться (например, «Согласовано для передачи в реестр» является
перекрывающимся статусом и не выделяется в едином столбце).
"""

from datetime import timedelta

from django.db.models import Case, CharField, Q, Value, When
from django.utils import timezone

# --- Константы статусов ---


SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "agreed_registry": "Согласовано для передачи в реестр",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
    "ready_18": "Готово к передаче в 18 отдел",
}

# Неизменяемые кортежи для констант
SAP_STAGE_NAMES = tuple(SAP_STAGE_LABELS.values())
SAP_STAGE_PARAMS = tuple(SAP_STAGE_LABELS.keys())

# Статусы, которые не выводятся как единый «Этап» в реестре,
# но учитываются в карточках дашборда
SAP_STAGES_OVERLAPPING = ("agreed_registry",)


# --- Условия для карточек дашборда ---


def sap_status_conditions():
    """Возвращает словарь Q-объектов для фильтрации заявок по статусам в карточках.

    Позволяет одной заявке попадать в несколько карточек одновременно.
    """
    today = timezone.localdate()
    return {
        "waiting_agreement": Q(
            stage_c__isnull=True,
            stage_e__isnull=True,
            stage_f__isnull=True,
            normalize_doc_num__isnull=True,
        ),
        "agreed_registry": Q(stage_c__isnull=False),
        "sent_18": Q(stage_e__isnull=False),
        "confirmed_18": Q(stage_f__isnull=False, normalize_doc_num__isnull=True),
        "paid": Q(normalize_doc_num__isnull=False),
        "ready_18": Q(stage_e__gt=today),
    }


def sap_date_field(status):
    """Возвращает имя поля даты, которое используется для фильтрации по конкретному статусу.

    Для 'agreed_registry' это stage_c, для 'waiting_agreement' — created_date,
    для остальных — stage_e (дата передачи в 18 отдел).
    """
    if status == "agreed_registry":
        return "stage_c"
    if status == "waiting_agreement":
        return "created_date"
    return "stage_e"


# --- Единый статус для реестра и графиков ---


def sap_status_expr():
    """Возвращает выражение Case/When для аннотации единого статуса заявки в ORM.

    Приоритет проверки:
    1. Оплачено (есть номер документа)
    2. Подтверждено 18 отделом (есть stage_f)
    3. На согласовании (нет stage_e)
    4. Готово к передаче в 18 отдел (stage_e в будущем)
    5. Передано в 18 отдел (по умолчанию, если stage_e есть и <= сегодня)
    """
    today = timezone.localdate()
    return Case(
        When(normalize_doc_num__isnull=False, then=Value("paid")),
        When(stage_f__isnull=False, then=Value("confirmed_18")),
        When(stage_e__isnull=True, then=Value("waiting_agreement")),
        When(stage_e__gt=today, then=Value("ready_18")),
        default=Value("sent_18"),
        output_field=CharField(),
    )


def sap_status_sql():
    """Возвращает SQL-фрагмент CASE для вычисления единого статуса в raw SQL.

    Логика идентична `sap_status_expr()`.
    """
    return """
        CASE
            WHEN normalize_doc_num IS NOT NULL THEN 'paid'
            WHEN stage_f IS NOT NULL THEN 'confirmed_18'
            WHEN stage_e IS NULL THEN 'waiting_agreement'
            WHEN stage_e > CURRENT_DATE THEN 'ready_18'
            ELSE 'sent_18'
        END
    """


# --- Утилиты дат ---


def sap_second_date(first_date):
    """Возвращает предыдущий рабочий день для заданной даты (без учёта праздников).

    Понедельник (0) -> пятница (-3 дня)
    Воскресенье (6) -> пятница (-2 дня)
    Остальные дни -> предыдущий день (-1 день)
    """
    weekday = first_date.weekday()
    if weekday == 0:
        offset = 3
    elif weekday == 6:
        offset = 2
    else:
        offset = 1
    return first_date - timedelta(days=offset)
