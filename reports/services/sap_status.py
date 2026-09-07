"""
Модуль для определения статуса заявок SAP на основе дат этапов.
Статусы:
- waiting_agreement: ожидание согласования (stage_e пусто)
- sent_18: передано в 18 отдел (stage_e заполнено, stage_f пусто, дата <= сегодня)
- ready_18: готово к передаче (stage_e заполнено, stage_f пусто, дата > сегодня)
- confirmed_18: подтверждено 18 отделом (stage_e и stage_f заполнены, но нет normalize_doc_num)
- paid: оплачено (stage_e, stage_f, normalize_doc_num заполнены)
"""

from datetime import timedelta

from django.db.models import Case, CharField, Q, Value, When
from django.utils import timezone

# Сопоставление внутреннего кода статуса -> человекочитаемая метка
SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
    "ready_18": "Готово к передаче в 18 отдел",
}

SAP_STAGE_NAMES = list(SAP_STAGE_LABELS.values())
SAP_STAGE_PARAMS = list(SAP_STAGE_LABELS.keys())


def sap_status_conditions():
    """
    Возвращает словарь {статус: Q-условие} для фильтрации queryset'а заявок SAP.
    Используется для построения карточек на сводке.
    """
    today = timezone.localdate()
    return {
        "waiting_agreement": Q(stage_e__isnull=True),
        "sent_18": Q(stage_e__isnull=False, stage_f__isnull=True, stage_e__lte=today),
        "confirmed_18": Q(
            stage_e__isnull=False,
            stage_f__isnull=False,
            normalize_doc_num__isnull=True,
        ),
        "paid": Q(
            stage_e__isnull=False,
            stage_f__isnull=False,
            normalize_doc_num__isnull=False,
        ),
        "ready_18": Q(stage_e__isnull=False, stage_f__isnull=True, stage_e__gt=today),
    }


def sap_status_expr():
    """
    Возвращает выражение Case/When для вычисления статуса в ORM.
    Порядок условий важен: сначала проверяются самые жёсткие (paid, confirmed_18),
    затем остальные.
    """
    today = timezone.localdate()
    return Case(
        When(stage_e__isnull=True, then=Value("waiting_agreement")),
        When(
            stage_f__isnull=False,
            normalize_doc_num__isnull=False,
            then=Value("paid"),
        ),
        When(stage_f__isnull=False, then=Value("confirmed_18")),
        When(stage_e__gt=today, then=Value("ready_18")),
        When(stage_e__isnull=False, then=Value("sent_18")),
        default=Value("waiting_agreement"),
        output_field=CharField(),
    )


def sap_second_date(first_date):
    """
    Вычисляет вторую дату для карточек SAP на основе дня недели первой даты.
    Используется для расчёта интервалов в отчётах.
    Если first_date — понедельник, то вторая дата = first_date - 3 дня.
    Если воскресенье, то -2 дня.
    В остальные дни -1 день.
    """
    if first_date is None:
        return None
    weekday = first_date.weekday()
    if weekday == 0:  # понедельник
        offset = 3
    elif weekday == 6:  # воскресенье
        offset = 2
    else:
        offset = 1
    return first_date - timedelta(days=offset)


def sap_status_sql():
    """
    Возвращает SQL-выражение CASE для вычисления статуса в сырых запросах.
    Логика полностью совпадает с sap_status_expr.
    """
    return """
            CASE
                WHEN stage_e IS NULL THEN 'waiting_agreement'
                WHEN stage_f IS NOT NULL AND normalize_doc_num IS NOT NULL THEN 'paid'
                WHEN stage_f IS NOT NULL THEN 'confirmed_18'
                WHEN stage_e > CURRENT_DATE THEN 'ready_18'
                WHEN stage_e IS NOT NULL THEN 'sent_18'
                ELSE 'waiting_agreement'
            END"""
