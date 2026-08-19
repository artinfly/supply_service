from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import Permission, User

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


class SectionChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.name.replace("Раздел: ", "")


class AccessUserForm(UserChangeForm):
    sections = SectionChoiceField(
        queryset=Permission.objects.filter(codename__startswith="access_"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Доступ к разделам",
        help_text="Отметьте разделы, которые будут видны этому пользователю.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["sections"].initial = self.instance.user_permissions.filter(
                codename__startswith="access_"
            )


admin.site.unregister(User)


@admin.register(User)
class UserWithSectionsAdmin(UserAdmin):
    form = AccessUserForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Личные данные", {"fields": ("first_name", "last_name", "email")}),
        ("Доступ к разделам", {"fields": ("sections",)}),
        ("Служебное", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Важные даты", {"fields": ("last_login", "date_joined")}),
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        keep = list(user.user_permissions.exclude(codename__startswith="access_"))
        user.user_permissions.set(keep + list(form.cleaned_data.get("sections") or []))
