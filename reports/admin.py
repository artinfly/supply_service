from django.contrib import admin
from .models import NsiCfo, NsiIgk, IgkStatData, StagingExcel, ContractsHistory


@admin.register(NsiCfo)
class NsiCfoAdmin(admin.ModelAdmin):
    list_display = ('cfo',)
    search_fields = ('cfo',)


@admin.register(NsiIgk)
class NsiIgkAdmin(admin.ModelAdmin):
    list_display = ('igk',)
    search_fields = ('igk',)


@admin.register(IgkStatData)
class IgkStatDataAdmin(admin.ModelAdmin):
    list_display = ('igk', 'c_agent', 'cfo', 'contract', 'status', 'y25', 'y26', 'y27')
    list_filter = ('status', 'payment_type', 'y25', 'y26', 'y27', 'is_deleted')
    search_fields = ('igk', 'c_agent', 'contract')


@admin.register(ContractsHistory)
class ContractsHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'old_status', 'new_status', 'update_date', 'upload_date')
    list_filter = ('update_date', 'upload_date')


@admin.register(StagingExcel)
class StagingExcelAdmin(admin.ModelAdmin):
    list_display = ('id', 'igk', 'dogovor', 'sostoyanie')