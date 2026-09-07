"""
Административный интерфейс для приложения reports.

Здесь регистрируются модели для отображения в админке Django,
а также кастомизируется форма редактирования пользователей для управления
правами доступа к разделам и интеграции с внешним API (сервис персонала).
"""

import logging

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
    IgkStatData,
    NsiIgk,
    Profile,
    StagingExcel,
    StagingZnpExcel,
    StagingZnpSAPExcel,
    ZnpData,
    ZnpDataSAP,
)

logger = logging.getLogger(__name__)

# API-адрес для интеграции с сервисом персонала
API_PATH = getattr(settings, "HR_SERVICE_API_URL", None)
BULK_SYNC_LIMIT = 100


@admin.register(NsiIgk)
class NsiIgkAdmin(admin.ModelAdmin):
    """Админка для справочника ИГК."""

    list_display = ("igk",)
    search_fields = ("igk",)


@admin.register(IgkStatData)
class IgkStatDataAdmin(admin.ModelAdmin):
    """Админка для позиций договоров."""

    list_display = ("igk", "c_agent", "cfo", "contract", "status", "y25", "y26", "y27")
    list_filter = ("status", "payment_type", "y25", "y26", "y27")
    search_fields = ("igk", "c_agent", "contract")


@admin.register(ContractsHistory)
class ContractsHistoryAdmin(admin.ModelAdmin):
    """Админка для истории изменений договоров."""

    list_display = ("id", "old_status", "new_status", "update_date", "upload_date")
    list_filter = ("update_date", "upload_date")


@admin.register(StagingExcel)
class StagingExcelAdmin(admin.ModelAdmin):
    """Админка для временных данных импорта договоров."""

    list_display = ("id", "igk", "dogovor", "sostoyanie")


@admin.register(StagingZnpExcel)
class StagingZnpExcelAdmin(admin.ModelAdmin):
    """Админка для временных данных импорта заявок ФЗД."""

    list_display = ("id", "igk", "c_agent", "contract", "plan_doc")
    search_fields = ("igk", "c_agent", "contract", "plan_doc")


@admin.register(StagingZnpSAPExcel)
class StagingZnpSAPExcelAdmin(admin.ModelAdmin):
    """Админка для временных данных импорта заявок SAP."""

    list_display = ("id", "reg_num", "igk", "cfo", "c_agent")
    search_fields = ("reg_num", "igk", "c_agent")


@admin.register(ZnpData)
class ZnpDataAdmin(admin.ModelAdmin):
    """Админка для заявок ФЗД."""

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
    """Админка для заявок SAP."""

    list_display = ("id", "reg_num", "igk", "cfo", "c_agent", "vv_sum")
    list_filter = ("cfo", "stage_e", "stage_f")
    search_fields = ("reg_num", "igk", "c_agent")


@admin.register(ContractCountsSnapshot)
class ContractCountsSnapshotAdmin(admin.ModelAdmin):
    """Админка для снимков количества договоров по датам."""

    list_display = ("upload_date", "igk", "cfo", "year_col", "concluded_count")
    list_filter = ("upload_date", "year_col")


# =============================================================================
# Кастомная админка пользователей с правами доступа к разделам
# =============================================================================


class SectionChoiceField(forms.ModelMultipleChoiceField):
    """
    Кастомное поле для выбора прав доступа к разделам.
    Отображает только название раздела (без префикса "Раздел: ").
    """

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
    """Форма редактирования пользователя с правами доступа к разделам."""

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


# Отменяем стандартную регистрацию User и регистрируем кастомную
admin.site.unregister(User)


@admin.register(User)
class UserWithSectionsAdmin(UserAdmin):
    """
    Кастомизированный администратор пользователей.

    Добавляет управление правами доступа к разделам и интеграцию
    с внешним сервисом персонала (синхронизация данных).
    """

    add_form = CustomUserCreationForm
    form = AccessUserForm
    add_form_template = "admin/auth/user/add_form.html"
    change_form_template = "admin/auth/user/change_form.html"

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

    # ---------- Кастомные методы для отображения полей профиля ----------

    def get_full_name(self, obj):
        """Возвращает полное ФИО (фамилия + имя + отчество)."""
        patronymic = (
            getattr(obj.profile, "patronymic", "") if hasattr(obj, "profile") else ""
        )
        parts = [obj.last_name, obj.first_name, patronymic]
        return " ".join(p for p in parts if p)

    get_full_name.short_description = "ФИО"
    get_full_name.admin_order_field = "last_name"

    def get_api_key(self, obj):
        return getattr(obj.profile, "api_key", "")

    get_api_key.short_description = "API ключ"
    get_api_key.admin_order_field = "profile__api_key"

    def get_is_fired(self, obj):
        return bool(getattr(obj.profile, "is_fired", False))

    get_is_fired.short_description = "Уволен?"
    get_is_fired.boolean = True
    get_is_fired.admin_order_field = "profile__is_fired"

    def get_last_synced_at(self, obj):
        return getattr(obj.profile, "last_synced_at", "")

    get_last_synced_at.short_description = "Дата синхронизации"
    get_last_synced_at.admin_order_field = "profile__last_synced_at"

    # ---------- Сохранение профиля и прав ----------

    def save_related(self, request, form, formsets, change):
        """
        Сохраняет права пользователя, оставляя существующие права,
        не связанные с разделами, и добавляя выбранные разделы.
        """
        super().save_related(request, form, formsets, change)
        user = form.instance
        keep = list(user.user_permissions.exclude(codename__startswith="access_"))
        user.user_permissions.set(keep + list(form.cleaned_data.get("sections") or []))

    def save_model(self, request, obj, form, change):
        """Сохраняет пользователя и обновляет профиль."""
        super().save_model(request, obj, form, change)
        Profile.objects.update_or_create(
            user=obj,
            defaults={
                "patronymic": form.cleaned_data.get("patronymic", ""),
                "api_key": form.cleaned_data.get("api_key", ""),
                "is_fired": form.cleaned_data.get("is_fired", False),
            },
        )

    # ---------- Интеграция с внешним API (сервис персонала) ----------

    def get_urls(self):
        """Добавляет кастомный URL для получения данных из внешнего API."""
        custom_urls = [
            path(
                "fetch-external-data/<str:tab_number>/",
                self.admin_site.admin_view(self.fetch_external_data),
                name="auth_user_fetch_external_data",
            ),
        ]
        return custom_urls + super().get_urls()

    def fetch_external_data(self, request, tab_number):
        """
        Получает данные о сотруднике из внешнего API по табельному номеру.
        Доступно только суперпользователям или для самого пользователя.
        """
        if not API_PATH:
            return JsonResponse({"error": "API-адрес не настроен"}, status=500)

        if not tab_number:
            return JsonResponse({"error": "Табельный номер не указан"}, status=400)

        # Проверяем, что запрос делает суперпользователь или сам сотрудник
        if not request.user.is_superuser and request.user.username != tab_number:
            return JsonResponse(
                {"error": "Нет прав на просмотр данных другого сотрудника"}, status=403
            )

        api_key = getattr(getattr(request.user, "profile", None), "api_key", None)
        if not api_key:
            return JsonResponse(
                {"error": "У текущего пользователя не задан API-ключ"}, status=400
            )

        url = f"{API_PATH}{tab_number}/"
        try:
            response = requests.get(url, headers={"X-API-Key": api_key}, timeout=5)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return JsonResponse({"error": f"Ошибка обращения к API: {e}"}, status=502)

        try:
            data = response.json()
        except ValueError:
            return JsonResponse({"error": "Некорректный ответ от API"}, status=502)

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
                "is_fired": data.get("is_fired", False),
                "api_key": data.get("api_key", ""),
            }
        )

    def sync_with_external_api(self, request, queryset):
        """
        Действие администратора: синхронизирует данные выбранных пользователей
        с внешним сервисом персонала (обновляет ФИО, статус увольнения, API-ключ).
        Ограничение: не более BULK_SYNC_LIMIT пользователей за один раз.
        """
        if not API_PATH:
            self.message_user(request, "API-адрес не настроен", level=messages.ERROR)
            return

        # Проверяем, что у текущего пользователя есть API-ключ
        api_key = getattr(getattr(request.user, "profile", None), "api_key", None)
        if not api_key:
            self.message_user(request, "У вас не задан API-ключ!", level=messages.ERROR)
            return

        total_selected = queryset.count()
        # Берем только первые BULK_SYNC_LIMIT записей (упорядоченных по дате синхронизации)
        queryset = queryset.select_related("profile").order_by(
            "profile__last_synced_at"
        )
        to_process = list(queryset[:BULK_SYNC_LIMIT])
        skipped = total_selected - len(to_process)

        update_count = 0
        error_count = 0

        for user in to_process:
            profile, _ = Profile.objects.get_or_create(user=user)
            tab_number = profile.user.username

            if not tab_number:
                profile.sync_error = "Не указано имя пользователя"
                profile.save(update_fields=["sync_error"])
                error_count += 1
                continue

            url = f"{API_PATH}{tab_number}/"
            try:
                response = requests.get(url, headers={"X-API-Key": api_key}, timeout=5)
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as e:
                profile.sync_error = str(e)
                profile.save(update_fields=["sync_error"])
                error_count += 1
                continue

            # Обновляем пользователя
            profile.user.first_name = data.get("name", profile.user.first_name)
            profile.user.last_name = data.get("surname", profile.user.last_name)
            profile.user.save(update_fields=["first_name", "last_name"])

            # Обновляем профиль
            profile.patronymic = data.get("patronymic", profile.patronymic)
            profile.is_fired = data.get("is_fired", profile.is_fired)
            profile.api_key = data.get("api_key", profile.api_key)
            profile.last_synced_at = timezone.now()
            profile.sync_error = ""
            profile.save()

            update_count += 1

        msg = f"Обновлено: {update_count}. Ошибок: {error_count}."
        if skipped > 0:
            msg += (
                f" Не обработано (превышен лимит {BULK_SYNC_LIMIT} за раз): {skipped}"
            )
        self.message_user(request, msg)

    sync_with_external_api.short_description = (
        f"Синхронизация с сервисом персонала (До {BULK_SYNC_LIMIT} за раз)"
    )
