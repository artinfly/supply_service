YEAR = "2026"
IGK = "2426187301032442228107"

PAGES = [
    ("root", []),
    ("dashboard", []),
    ("kdr_table", [YEAR]),
    ("igk_concluded_table", [YEAR]),
    ("igk_not_concluded_table", [YEAR]),
    ("igk_terminated_table", [YEAR]),
    ("all_contracts_table", []),
    ("znp_table", []),
    ("znp_list_table", []),
    ("znp_sap_table", []),
    ("znp_sap_list_table", []),
    ("history_status_table", []),
    ("history_plan_table", []),
    ("history_fact_table", []),
    ("contract_dupes_table", []),
    ("upload_excel", []),
    ("export_page", []),
]

EXPORTS = [
    ("export_advances", [YEAR]),
    ("export_kdr", [YEAR]),
    ("export_contracts_by_agent", [YEAR]),
    ("export_history_status", []),
    ("export_history_plan", []),
    ("export_history_fact", []),
    ("export_contract_dupes", []),
]

APIS = [
    ("api_kdr", [YEAR]),
    ("api_igk_concluded", [YEAR]),
    ("api_igk_not_concluded", [YEAR]),
    ("api_igk_terminated", [YEAR]),
    ("api_all_contracts", []),
    ("api_znp_list", []),
    ("api_znp_sap_list", []),
    ("api_history_status", []),
    ("api_history_plan", []),
    ("api_history_fact", []),
    ("api_contract_dupes", []),
    ("api_contract_dupes_by_order", []),
    ("api_igk_detail", [YEAR, IGK]),
    ("api_chart_contracts", []),
    ("api_chart_znp", []),
    ("api_chart_znp_sap", []),
]

ALL = PAGES + EXPORTS + APIS
