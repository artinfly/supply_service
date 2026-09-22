"""
Статусы заявок на платёж SAP.

Логика статусов основана на датах этапов (stage_e, stage_f) и наличии
нормализованного номера документа (normalize_doc_num).

ВАЖНО: stage_e в текущих данных не заполняется, поэтому статусы
sent_18 и ready_18 не вычисляются. При появлении данных в stage_e
необходимо вернуть полную логику (см. историю коммитов).
"""

from datetime import timedelta

from django.db.models import Case, CharField, Q, Value, When

# --- Константы ---

SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
    "ready_18": "Готово к передаче в 18 отдел",
}

SAP_STAGE_NAMES = list(SAP_STAGE_LABELS.values())
SAP_STAGE_PARAMS = list(SAP_STAGE_LABELS.keys())


# --- Условия для ORM-запросов ---


def sap_status_conditions():
    """
    Условия Q для определения статуса заявки через ORM.

    Без stage_e доступно только три статуса:
    waiting_agreement, confirmed_18, paid.
    """
    return {
        "waiting_agreement": Q(stage_f__isnull=True, normalize_doc_num__isnull=True),
        "confirmed_18": Q(stage_f__isnull=False, normalize_doc_num__isnull=True),
        "paid": Q(normalize_doc_num__isnull=False),
    }


def sap_status_expr():
    """
    Выражение CASE для определения статуса заявки через ORM.

    Без stage_e доступно только три статуса:
    waiting_agreement, confirmed_18, paid.
    """
    return Case(
        When(normalize_doc_num__isnull=False, then=Value("paid")),
        When(stage_f__isnull=False, then=Value("confirmed_18")),
        default=Value("waiting_agreement"),
        output_field=CharField(),
    )


# --- SQL для запросов ---


def sap_status_sql():
    """SQL-выражение CASE для определения статуса заявки (для charts.py)."""
    return """
        CASE
            WHEN normalize_doc_num IS NOT NULL THEN 'paid'
            WHEN stage_f IS NOT NULL THEN 'confirmed_18'
            ELSE 'waiting_agreement'
        END
    """


# --- Вспомогательные функции ---


def sap_second_date(first_date):
    """
    Вычисляет вторую дату карточек SAP от первой даты (из фильтра).
    Смещение зависит от дня недели первой даты.
    """
    weekday = first_date.weekday()
    if weekday == 0:
        offset = 3
    elif weekday == 6:
        offset = 2
    else:
        offset = 1
    return first_date - timedelta(days=offset)
