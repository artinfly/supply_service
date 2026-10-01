"""
Статусы заявок на платёж SAP.

Карточки сводки и фильтры реестра считаются независимо: одна заявка
может попасть сразу в несколько карточек. Условия заданы в одном месте —
sap_status_conditions(), поле даты для фильтра — в sap_date_field().

Подпись «Этап» в реестре и стек графика показывают ОДИН статус на заявку
(sap_status_expr() и sap_status_sql()), поэтому их числа могут отличаться
от карточек.

ВАЖНО: sap_status_expr() и sap_status_sql() должны совпадать между собой.
"""

from datetime import timedelta

from django.db.models import Case, CharField, Q, Value, When
from django.utils import timezone

# --- Константы ---

SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "agreed_registry": "Согласовано для передачи в реестр",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
    "ready_18": "Готово к передаче в 18 отдел",
}

SAP_STAGE_NAMES = list(SAP_STAGE_LABELS.values())
SAP_STAGE_PARAMS = list(SAP_STAGE_LABELS.keys())

# Карточки, которых нет в стеке графика (пересекаются с остальными)
SAP_STAGES_OVERLAPPING = ("agreed_registry",)


# --- Условия для ORM-запросов ---


def sap_status_conditions():
    """Условия карточек сводки и фильтров реестра. Карточки независимы."""
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
    """Поле даты, по которому статус фильтруется при выбранной дате."""
    if status == "agreed_registry":
        return "stage_c"
    if status == "waiting_agreement":
        return "created_date"
    return "stage_e"


def sap_status_expr():
    """Аннотация с одним статусом на заявку (для подписи в списке)."""
    today = timezone.localdate()
    return Case(
        When(normalize_doc_num__isnull=False, then=Value("paid")),
        When(stage_f__isnull=False, then=Value("confirmed_18")),
        When(stage_e__isnull=True, then=Value("waiting_agreement")),
        When(stage_e__gt=today, then=Value("ready_18")),
        default=Value("sent_18"),
        output_field=CharField(),
    )


# --- SQL для запросов ---


def sap_status_sql():
    """Тот же статус, что и в sap_status_expr(), для сырого SQL."""
    return """
            CASE
                WHEN normalize_doc_num IS NOT NULL THEN 'paid'
                WHEN stage_f IS NOT NULL THEN 'confirmed_18'
                WHEN stage_e IS NULL THEN 'waiting_agreement'
                WHEN stage_e > CURRENT_DATE THEN 'ready_18'
                ELSE 'sent_18'
            END"""


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
