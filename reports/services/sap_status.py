from django.db.models import Case, CharField, Q, Value, When
from django.utils import timezone

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
    today = timezone.localdate()
    return {
        "waiting_agreement": Q(stage_e__isnull=True),
        "sent_18": Q(stage_e__isnull=False, stage_f__isnull=True, stage_e__lte=today),
        "confirmed_18": Q(
            stage_e__isnull=False, stage_f__isnull=False, normalize_doc_num__isnull=True
        ),
        "paid": Q(
            stage_e__isnull=False,
            stage_f__isnull=False,
            normalize_doc_num__isnull=False,
        ),
        "ready_18": Q(stage_e__isnull=False, stage_f__isnull=True, stage_e__gt=today),
    }


def sap_status_expr():
    today = timezone.localdate()
    return Case(
        When(stage_e__isnull=True, then=Value("waiting_agreement")),
        When(
            stage_f__isnull=False, normalize_doc_num__isnull=False, then=Value("paid")
        ),
        When(stage_f__isnull=False, then=Value("confirmed_18")),
        When(stage_e__gt=today, then=Value("ready_18")),
        When(stage_e__isnull=False, then=Value("sent_18")),
        default=Value("waiting_agreement"),
        output_field=CharField(),
    )


def sap_status_sql():
    return """
            CASE
                WHEN stage_e IS NULL THEN 'waiting_agreement'
                WHEN stage_f IS NOT NULL AND normalize_doc_num IS NOT NULL THEN 'paid'
                WHEN stage_f IS NOT NULL THEN 'confirmed_18'
                WHEN stage_e > CURRENT_DATE THEN 'ready_18'
                WHEN stage_e IS NOT NULL THEN 'sent_18'
                ELSE 'waiting_agreement'
            END"""
