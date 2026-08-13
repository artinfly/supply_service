from django.contrib import admin

from .models import (
    ContractCountsSnapshot,
    ContractsHistory,
    IgkStatData,
    NsiIgk,
    StagingExcel,
    StagingZnpExcel,
    StagingZnpSAPExcel,
    ZnpData,
    ZnpDataSAP,
)


@admin.register(NsiIgk)
class NsiIgkAdmin(admin.ModelAdmin):
    list_display = ("igk",)
    search_fields = ("igk",)


@admin.register(IgkStatData)
class IgkStatDataAdmin(admin.ModelAdmin):
    list_display = ("igk", "c_agent", "cfo", "contract", "status", "y25", "y26", "y27")
    list_filter = ("status", "payment_type", "y25", "y26", "y27")
    search_fields = ("igk", "c_agent", "contract")


@admin.register(ContractsHistory)
class ContractsHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "old_status", "new_status", "update_date", "upload_date")
    list_filter = ("update_date", "upload_date")


@admin.register(StagingExcel)
class StagingExcelAdmin(admin.ModelAdmin):
    list_display = ("id", "igk", "dogovor", "sostoyanie")


@admin.register(StagingZnpExcel)
class StagingZnpExcelAdmin(admin.ModelAdmin):
    list_display = ("id", "igk", "c_agent", "contract", "plan_doc")
    search_fields = ("igk", "c_agent", "contract", "plan_doc")


@admin.register(ZnpData)
class ZnpDataAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "plan_doc",
        "parent",
        "plan_payment_date",
        "fact_payment_date",
    )
    list_filter = ("plan_payment_date", "fact_payment_date")
    search_fields = ("plan_doc", "payment_purpose")


@admin.register(ContractCountsSnapshot)
class ContractCountsSnapshotAdmin(admin.ModelAdmin):
    list_display = ("upload_date", "igk", "cfo", "year_col", "concluded_count")
    list_filter = ("upload_date", "year_col")


@admin.register(ZnpDataSAP)
class ZnpDataSAPAdmin(admin.ModelAdmin):
    list_display = ("id", "reg_num", "igk", "cfo", "c_agent", "vv_sum")
    list_filter = ("cfo", "stage_e", "stage_f")
    search_fields = ("reg_num", "igk", "c_agent")


@admin.register(StagingZnpSAPExcel)
class StagingZnpSAPExcelAdmin(admin.ModelAdmin):
    list_display = ("id", "reg_num", "igk", "cfo", "c_agent")
    search_fields = ("reg_num", "igk", "c_agent")
