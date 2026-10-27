"""Админка: регистрация моделей, кастомные формы пользователей, синхронизация с HR."""

import requests
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Permission, User
from django.http import JsonResponse
from django.urls import path
from django.utils import timezone

from .models import (
    ContractCountsSnapshot,
    ContractsHistory,
    GozContractVat,
    IgkStatData,
    NsiIgk,
    Profile,
    StagingExcel,
    StagingZnpExcel,
    StagingZnpSAPExcel,
    SystemEvent,
    ZnpData,
    ZnpDataSAP,
)

# --- Константы ---
API_PATH = settings.HR_SERVICE_API_URL
BULK_SYNC_LIMIT = 100


# --- Простые админки для моделей ---


@admin.register(NsiIgk)
class NsiIgkAdmin(admin.ModelAdmin):
    list_display = ("igk",)
    search_fields = ("igk",)


@admin.register(GozContractVat)
class GozContractVatAdmin(admin.ModelAdmin):
    list_display = ("igk", "enterprise", "order", "contract_date", "vat_rate")
    search_fields = ("igk", "enterprise", "order", "contract_date")
    ordering = ("igk",)


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


@admin.register(StagingZnpSAPExcel)
class StagingZnpSAPExcelAdmin(admin.ModelAdmin):
    list_display = ("id", "reg_num", "igk", "cfo", "c_agent")
    search_fields = ("reg_num", "igk", "c_agent")


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


@admin.register(ZnpDataSAP)
class ZnpDataSAPAdmin(admin.ModelAdmin):
    list_display = ("id", "reg_num", "igk", "cfo", "c_agent", "vv_sum")
    list_filter = ("cfo", "stage_e", "stage_f")
    search_fields = ("reg_num", "igk", "c_agent")


@admin.register(ContractCountsSnapshot)
class ContractCountsSnapshotAdmin(admin.ModelAdmin):
    list_display = ("upload_date", "igk", "cfo", "year_col", "concluded_count")
    list_filter = ("upload_date", "year_col")


# --- Кастомные формы для пользователей ---


class SectionChoiceField(forms.ModelMultipleChoiceField):
    """Поле выбора прав доступа с очищенными названиями."""

    def label_from_instance(self, obj):
        return obj.name.replace("Раздел: ", "")


class CustomUserCreationForm(UserCreationForm):
    """Форма создания пользователя с дополнительными полями профиля."""

    patronymic = forms.CharField(label="Отчество", max_length=255, required=False)
    api_key = forms.CharField(label="API-ключ", max_length=64, required=False)
    is_fired = forms.BooleanField(
        label="Уволен?", required=False, widget=forms.CheckboxInput
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name")


class AccessUserForm(UserChangeForm):
    """Форма редактирования пользователя с правами доступа и полями профиля."""

    patronymic = forms.CharField(label="Отчество", max_length=255, required=False)
    api_key = forms.CharField(label="API-ключ", max_length=64, required=False)
    is_fired = forms.BooleanField(
        label="Уволен?", required=False, widget=forms.CheckboxInput
    )

    sections = SectionChoiceField(
        queryset=Permission.objects.filter(codename__startswith="access_"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Доступ к разделам",
        help_text="Отметьте разделы, которые будут видны этому пользователю.",
    )

    class Meta:
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["sections"].initial = self.instance.user_permissions.filter(
                codename__startswith="access_"
            )
            profile, _ = Profile.objects.get_or_create(user=self.instance)
            self.fields["patronymic"].initial = profile.patronymic
            self.fields["api_key"].initial = profile.api_key
            self.fields["is_fired"].initial = profile.is_fired


# --- Кастомная админка пользователей ---


admin.site.unregister(User)


@admin.register(User)
class UserWithSectionsAdmin(UserAdmin):
    """Админка пользователей с правами доступа и синхронизацией с HR."""

    add_form = CustomUserCreationForm
    form = AccessUserForm

    list_display = (
        "username",
        "get_full_name",
        "is_active",
        "is_superuser",
        "get_is_fired",
        "get_last_synced_at",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "profile__is_fired")
    actions = ["sync_with_external_api"]

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Личные данные",
            {
                "fields": (
                    "last_name",
                    "first_name",
                    "patronymic",
                    "api_key",
                    "is_fired",
                )
            },
        ),
        ("Доступ к разделам", {"fields": ("sections",)}),
        ("Служебное", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Важные даты", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "last_name",
                    "first_name",
                    "patronymic",
                    "is_fired",
                    "api_key",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile")

    # У пользователей, созданных до появления профилей, записи Profile может
    # не быть: obj.profile тогда бросает исключение. getattr(obj, "profile", None)
    # его гасит (RelatedObjectDoesNotExist — подкласс AttributeError).

    @admin.display(description="ФИО", ordering="last_name")
    def get_full_name(self, obj):
        patronymic = getattr(getattr(obj, "profile", None), "patronymic", "")
        parts = [obj.last_name, obj.first_name, patronymic]
        return " ".join(p for p in parts if p)

    @admin.display(description="Уволен?", boolean=True, ordering="profile__is_fired")
    def get_is_fired(self, obj):
        return bool(getattr(getattr(obj, "profile", None), "is_fired", False))

    @admin.display(description="Дата синхронизации", ordering="profile__last_synced_at")
    def get_last_synced_at(self, obj):
        return getattr(getattr(obj, "profile", None), "last_synced_at", "")

    def save_related(self, request, form, formsets, change):
        """Права на разделы (access_*) берутся из галочек «Доступ к разделам»;
        остальные права пользователя не трогаются."""
        super().save_related(request, form, formsets, change)
        user = form.instance
        keep = list(user.user_permissions.exclude(codename__startswith="access_"))
        user.user_permissions.set(keep + list(form.cleaned_data.get("sections") or []))

    def save_model(self, request, obj, form, change):
        """Поля профиля (отчество, API-ключ, «уволен») лежат в отдельной модели Profile."""
        super().save_model(request, obj, form, change)
        Profile.objects.update_or_create(
            user=obj,
            defaults={
                "patronymic": form.cleaned_data.get("patronymic", ""),
                "api_key": form.cleaned_data.get("api_key", ""),
                "is_fired": form.cleaned_data.get("is_fired", False),
            },
        )

    def get_urls(self):
        custom_urls = [
            path(
                "fetch-external-data/<str:tab_number>/",
                self.admin_site.admin_view(self.fetch_external_data),
                name="auth_user_fetch_external_data",
            ),
        ]
        return custom_urls + super().get_urls()

    @staticmethod
    def _fetch_from_hr_api(tab_number, api_key):
        """Запрос к HR API по табельному номеру.

        API-ключ передаётся явно: объект админки один на всех пользователей,
        поэтому хранить ключ в его атрибуте нельзя — запросы разных людей
        перемешались бы.

        Returns:
            (data, None) при успехе или (None, (текст_ошибки, http_статус)).
        """
        if not API_PATH:
            return None, ("HR_SERVICE_API_URL не задан", 500)

        url = f"{API_PATH}{tab_number}/"
        try:
            response = requests.get(url, headers={"X-API-Key": api_key}, timeout=5)
            response.raise_for_status()
            return response.json(), None
        except requests.RequestException as e:
            return None, (f"Ошибка обращения к API: {e}", 502)
        except ValueError:
            return None, ("Некорректный ответ от API", 502)

    @staticmethod
    def _request_api_key(request):
        """API-ключ текущего администратора (из его профиля) или None."""
        return getattr(getattr(request.user, "profile", None), "api_key", None)

    def fetch_external_data(self, request, tab_number):
        """Кнопка «Получить данные сотрудника» в форме пользователя (AJAX)."""
        api_key = self._request_api_key(request)
        if not api_key:
            return JsonResponse(
                {"error": "У текущего пользователя не задан API-ключ"}, status=400
            )

        data, error = self._fetch_from_hr_api(tab_number, api_key)
        if error:
            text, status = error
            return JsonResponse({"error": text}, status=status)

        return JsonResponse(
            {
                "surname": data.get("surname", ""),
                "name": data.get("name", ""),
                "patronymic": data.get("patronymic", ""),
                "birth_date": data.get("birth_date", ""),
                "hire_date": data.get("hire_date", ""),
                "dismissal_date": data.get("dismissal_date", ""),
                "production": data.get("production", ""),
                "department": data.get("department", ""),
                "position": data.get("position", ""),
                "is_fired": data.get("is_fired", ""),
                "api_key": data.get("api_key", ""),
            }
        )

    def sync_with_external_api(self, request, queryset):
        """Массовая синхронизация пользователей с HR-системой."""
        queryset = queryset.select_related("profile").order_by(
            "profile__last_synced_at"
        )
        total_selected = queryset.count()
        to_process = list(queryset[:BULK_SYNC_LIMIT])

        update_count = 0
        error_count = 0

        api_key = self._request_api_key(request)
        if not api_key:
            self.message_user(request, "У вас не задан API-ключ!", level=messages.ERROR)
            return

        for user in to_process:
            profile, _ = Profile.objects.get_or_create(user=user)
            tab_number = profile.user.username

            if not tab_number:
                profile.sync_error = "Не указано имя пользователя"
                profile.save(update_fields=["sync_error"])
                error_count += 1
                continue

            data, error = self._fetch_from_hr_api(tab_number, api_key)
            if error:
                # Раньше сюда попадал repr объекта JsonResponse, а не текст ошибки
                profile.sync_error = error[0]
                profile.save(update_fields=["sync_error"])
                error_count += 1
                continue

            profile.user.first_name = data.get("name", profile.user.first_name)
            profile.user.last_name = data.get("surname", profile.user.last_name)
            profile.user.save(update_fields=["first_name", "last_name"])

            profile.patronymic = data.get("patronymic", profile.patronymic)
            profile.is_fired = data.get("is_fired", profile.is_fired)
            profile.api_key = data.get("api_key", profile.api_key)
            profile.last_synced_at = timezone.now()
            profile.sync_error = ""
            profile.save()

            update_count += 1

        skipped = total_selected - len(to_process)
        msg = f"Обновлено: {update_count}. Ошибок: {error_count}."
        if skipped > 0:
            msg += f" Не обработано (превышен лимит {BULK_SYNC_LIMIT}): {skipped}"
        self.message_user(request, msg)

    sync_with_external_api.short_description = (
        f"Синхронизация с сервисом персонала (до {BULK_SYNC_LIMIT} за раз)"
    )


@admin.register(SystemEvent)
class SystemEventAdmin(admin.ModelAdmin):
    """Время последних загрузок (только просмотр: события пишут команды загрузки)."""

    list_display = ("event_key", "event_time")
    list_filter = ("event_key",)
    search_fields = ("event_key",)
    date_hierarchy = "event_time"
    fields = ("event_key", "event_time")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
