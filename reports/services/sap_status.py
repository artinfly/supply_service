from django.db.models import Case, CharField, Q, Value, When

SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
}

SAP_STAGE_NAMES = list(SAP_STAGE_LABELS.values())

SAP_STAGE_PARAMS = list(SAP_STAGE_LABELS.keys())

SAP_STATUS_CONDITIONS = {
    "waiting_agreement": Q(stage_e__isnull=True),
    "sent_18": Q(stage_e__isnull=False, stage_f__isnull=True),
    "confirmed_18": Q(
        stage_e__isnull=False, stage_f__isnull=False, normalize_doc_num__isnull=True
    ),
    "paid": Q(
        stage_e__isnull=False, stage_f__isnull=False, normalize_doc_num__isnull=False
    ),
}

sap_status_expr = Case(
    When(stage_e__isnull=True, then=Value("waiting_agreement")),
    When(stage_f__isnull=True, then=Value("sent_18")),
    When(normalize_doc_num__isnull=False, then=Value("paid")),
    default=Value("confirmed_18"),
    output_field=CharField(),
)

SAP_STATUS_SQL = """
               CASE
                   WHEN stage_e IS NULL THEN 'waiting_agreement'
                   WHEN stage_f IS NULL THEN 'sent_18'
                   WHEN normalize_doc_num IS NOT NULL THEN 'paid'
                   ELSE 'confirmed_18'
               END"""
