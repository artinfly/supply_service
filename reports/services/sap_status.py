# Статус заявки SAP по датам этапов. Одно место на два применения:
# выражение для запроса и функция для построчной подписи в JSON.
from django.db.models import Case, CharField, Q, Value, When

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


def sap_status(stage_e, stage_f, normalize_doc_num):
    if stage_e is None:
        return "waiting_agreement"
    if stage_f is None:
        return "sent_18"
    if normalize_doc_num is not None:
        return "paid"
    return "confirmed_18"
