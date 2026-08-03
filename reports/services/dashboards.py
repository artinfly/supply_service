# Расчёты для дашбордов: карточки сверху и таблица по ЦФО.
# Одни и те же числа считаются здесь для сводки и для строк по ЦФО.
def to_mln(value):
    return (value or 0) / 1000000


def percent(part, whole):
    return (part / whole * 100) if whole else 0


def filter_by_year(queryset, year, field_prefix=""):
    field_name = f"{field_prefix}y{str(year)[-2:]}"
    return queryset.filter(**{field_name: True})


EMPTY_CFO_STATS = {
    "all_count": 0,
    "all_sum": None,
    "all_concluded_count": 0,
    "all_concluded_sum": None,
    "curr_count": 0,
    "curr_sum": None,
    "curr_concluded_count": 0,
    "curr_concluded_sum": None,
    "curr_not_concluded_count": 0,
    "curr_not_concluded_sum": None,
    "curr_plan": None,
    "curr_fact": None,
}

CFO_SUMMED = (
    "all_count",
    "all_sum",
    "all_concluded_count",
    "all_concluded_sum",
    "year_count",
    "year_sum",
    "year_concluded_count",
    "year_concluded_sum",
    "year_not_concluded_count",
    "year_not_concluded_sum",
    "advance_plan",
    "advance_fact",
)


def cfo_row(label, s):
    row = {
        "cfo": label,
        "all_count": s["all_count"],
        "all_sum": to_mln(s["all_sum"]),
        "all_concluded_count": s["all_concluded_count"],
        "all_concluded_sum": to_mln(s["all_concluded_sum"]),
        "year_count": s["curr_count"],
        "year_sum": to_mln(s["curr_sum"]),
        "year_concluded_count": s["curr_concluded_count"],
        "year_concluded_sum": to_mln(s["curr_concluded_sum"]),
        "year_not_concluded_count": s["curr_not_concluded_count"],
        "year_not_concluded_sum": to_mln(s["curr_not_concluded_sum"]),
        "advance_plan": to_mln(s["curr_plan"]),
        "advance_fact": to_mln(s["curr_fact"]),
    }
    return with_cfo_percents(row)


def with_cfo_percents(row):
    row["year_concluded_percent"] = percent(
        row["year_concluded_count"], row["year_count"]
    )
    row["year_concluded_sum_percent"] = percent(
        row["year_concluded_sum"], row["year_sum"]
    )
    row["advance_percent"] = percent(row["advance_fact"], row["advance_plan"])
    return row


def cfo_totals_row(rows):
    totals = {"cfo": "ИТОГО"}
    for key in CFO_SUMMED:
        totals[key] = sum(r[key] for r in rows)
    return with_cfo_percents(totals)


ZNP_STAGE_LABELS = {
    "not_issued_advance": "Не оформлено (Аванс)",
    "not_issued_postpayment": "Не оформлено (Постоплата)",
    "in_progress": "На оформлении ЗнП",
    "advance": "Оформлено ЗнП (Аванс)",
    "advance_paid": "Оплачено ЗнП (Аванс)",
    "postpayment": "Оформлено ЗнП (Постоплата)",
    "postpayment_paid": "Оплачено ЗнП (Постоплата)",
}

ZNP_STAGE_NAMES = list(ZNP_STAGE_LABELS.values())

EMPTY_NOT_ISSUED = {
    "count": 0,
    "plan_sum": None,
    "advance_count": 0,
    "advance_sum": None,
    "postpayment_count": 0,
    "postpayment_sum": None,
}

EMPTY_ZNP = {
    "issued_count": 0,
    "issued_sum": None,
    "in_progress_count": 0,
    "in_progress_sum": None,
    "advance_count": 0,
    "advance_sum": None,
    "advance_paid_count": 0,
    "advance_paid_sum": None,
    "postpayment_count": 0,
    "postpayment_sum": None,
    "postpayment_paid_count": 0,
    "postpayment_paid_sum": None,
}


def breakdown_from_stats(ni, zs):
    not_issued_count = ni["count"] or 0
    not_issued_sum = to_mln(ni["plan_sum"])
    not_issued_advance_count = ni["advance_count"] or 0
    not_issued_postpayment_count = ni["postpayment_count"] or 0

    issued_count = zs["issued_count"] or 0
    issued_sum = to_mln(zs["issued_sum"])
    in_progress_count = zs["in_progress_count"] or 0
    advance_count = zs["advance_count"] or 0
    advance_paid_count = zs["advance_paid_count"] or 0
    postpayment_count = zs["postpayment_count"] or 0
    postpayment_paid_count = zs["postpayment_paid_count"] or 0

    total = not_issued_count + issued_count + in_progress_count

    def _pct(part, whole):
        return (part / whole * 100) if whole else 0

    def _card(count, plan_sum, status_param, percent=None):
        return {
            "count": count,
            "sum": plan_sum,
            "percent": _pct(count, total) if percent is None else percent,
            "status_param": status_param,
        }

    return {
        "total_count": total,
        "total_sum": not_issued_sum + issued_sum + to_mln(zs["in_progress_sum"]),
        "not_issued": _card(not_issued_count, not_issued_sum, "not_issued"),
        "not_issued_advance": _card(
            not_issued_advance_count,
            to_mln(ni["advance_sum"]),
            "not_issued_advance",
        ),
        "not_issued_postpayment": _card(
            not_issued_postpayment_count,
            to_mln(ni["postpayment_sum"]),
            "not_issued_postpayment",
        ),
        "issued": _card(issued_count, issued_sum, "advance,postpayment"),
        "in_progress": _card(
            in_progress_count,
            to_mln(zs["in_progress_sum"]),
            "in_progress",
        ),
        "advance": _card(
            advance_count,
            to_mln(zs["advance_sum"]),
            "advance",
            percent=_pct(advance_count, issued_count),
        ),
        "advance_paid": _card(
            advance_paid_count,
            to_mln(zs["advance_paid_sum"]),
            "advance_paid",
            percent=_pct(advance_paid_count, advance_count),
        ),
        "postpayment": _card(
            postpayment_count,
            to_mln(zs["postpayment_sum"]),
            "postpayment",
            percent=_pct(postpayment_count, issued_count),
        ),
        "postpayment_paid": _card(
            postpayment_paid_count,
            to_mln(zs["postpayment_paid_sum"]),
            "postpayment_paid",
            percent=_pct(postpayment_paid_count, postpayment_count),
        ),
    }


SAP_STAGE_LABELS = {
    "waiting_agreement": "На согласовании",
    "sent_18": "Передано в 18 отдел",
    "confirmed_18": "Подтверждено 18 отделом",
    "paid": "Оплачено",
}

SAP_STAGE_NAMES = list(SAP_STAGE_LABELS.values())

SAP_STAGE_PARAMS = list(SAP_STAGE_LABELS.keys())


def sap_cards(total_row, status_rows):
    total = (total_row or {}).get("total") or 0
    total_sum = ((total_row or {}).get("total_sum") or 0) / 1000000

    def _card(status):
        row = status_rows.get(status)
        count = (row or {}).get("count") or 0
        vv_sum = ((row or {}).get("vv_sum") or 0) / 1000000
        return {
            "count": count,
            "sum": vv_sum,
            "percent": (count / total * 100) if total else 0,
            "status_param": status,
        }

    return {
        "total_count": total,
        "total_sum": total_sum,
        **{status: _card(status) for status in SAP_STAGE_PARAMS},
    }
