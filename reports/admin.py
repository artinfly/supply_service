import requests
from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Permission, User
from django.http import JsonResponse
from django.urls import path

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

API_PATH = settings.HR_SERVICE_API_URL


@admin.register(NsiIgk)
class NsiIgkAdmin(admin.ModelAdmin):
    """Админка для справочника ИГК."""

    # Колонки в списке
    list_display = ("igk",)
    # Поля для поиска
    search_fields = ("igk",)


@admin.register(IgkStatData)
class IgkStatDataAdmin(admin.ModelAdmin):
    """
    Админка для позиций договоров.

    Показывает основные поля и позволяет фильтровать по статусу,
    типу платежа и годам. Используется для отладки и просмотра данных.
    """

    # Колонки в списке: основные поля позиции
    list_display = ("igk", "c_agent", "cfo", "contract", "status", "y25", "y26", "y27")
    # Фильтры в правой панели
    list_filter = ("status", "payment_type", "y25", "y26", "y27")
    # Поля для поиска
    search_fields = ("igk", "c_agent", "contract")


@admin.register(ContractsHistory)
class ContractsHistoryAdmin(admin.ModelAdmin):
    """
    Админка для истории изменений договоров.

    Показывает изменения статуса с датами. Используется для просмотра
    и отладки истории изменений.
    """

    # Колонки в списке: изменение статуса и даты
    list_display = ("id", "old_status", "new_status", "update_date", "upload_date")
    # Фильтры по датам
    list_filter = ("update_date", "upload_date")


# ============================================================================
# Staging таблицы (импорт)
# ============================================================================


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


# ============================================================================
# Рабочие таблицы заявок
# ============================================================================


@admin.register(ZnpData)
class ZnpDataAdmin(admin.ModelAdmin):
    """
    Админка для заявок ФЗД.

    Показывает плановый документ и связь с позицией договора (parent).
    Позволяет проверять корректность привязки заявок.
    """

    list_display = (
        "id",
        "plan_doc",
        "parent",  # Связь с позицией договора
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


# ============================================================================
# Кастомная админка пользователей с правами доступа к разделам
# ============================================================================


class SectionChoiceField(forms.ModelMultipleChoiceField):
    """
    Кастомное поле для выбора прав доступа к разделам.

    Наследуется от ModelMultipleChoiceField, чтобы переопределить
    отображение меток. Вместо полного названия права ("Раздел: Договорная работа")
    показываем только название раздела ("Договорная работа").
    """

    def label_from_instance(self, obj):
        """Убирает префикс "Раздел: " из названия права."""
        return obj.name.replace("Раздел: ", "")


class CustomUserCreationForm(UserCreationForm):
    patronymic = forms.CharField(label="Отчество", max_length=255, required=False)
    api_key = forms.CharField(label="API-ключ", max_length=64, required=False)
    is_fired = forms.BooleanField(
        label="Уволен?", required=False, widget=forms.CheckboxInput
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name")


class AccessUserForm(UserChangeForm):
    patronymic = forms.CharField(label="Отчество", max_length=255, required=False)
    api_key = forms.CharField(label="API-ключ", max_length=64, required=False)
    is_fired = forms.BooleanField(
        label="Уволен?", required=False, widget=forms.CheckboxInput
    )

    sections = SectionChoiceField(
        # Все права, начинающиеся с "access_"
        queryset=Permission.objects.filter(codename__startswith="access_"),
        # Отображение в виде чекбоксов (не выпадающего списка)
        widget=forms.CheckboxSelectMultiple,
        # Необязательное поле — пользователь может не иметь доступа
        required=False,
        label="Доступ к разделам",
        help_text="Отметьте разделы, которые будут видны этому пользователю.",
    )

    class Meta:
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        """Инициализация формы с предустановленными значениями."""
        super().__init__(*args, **kwargs)
        # Если редактируем существующего пользователя, загружаем его текущие права
        if self.instance.pk:
            self.fields["sections"].initial = self.instance.user_permissions.filter(
                codename__startswith="access_"
            )

            profile, _ = Profile.objects.get_or_create(user=self.instance)
            self.fields["patronymic"].initial = profile.patronymic
            self.fields["api_key"].initial = profile.api_key
            self.fields["is_fired"].initial = profile.is_fired


# Отменяем стандартную регистрацию модели User, чтобы заменить на кастомную
admin.site.unregister(User)


@admin.register(User)
class UserWithSectionsAdmin(UserAdmin):
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
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "profile__is_fired")

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

    def get_full_name(self, obj):
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

    def save_related(self, request, form, formsets, change):
        """
        Переопределяет сохранение связанных объектов (включая права).

        Сохраняет все права пользователя, НЕ начинающиеся с "access_",
        и добавляет выбранные права доступа к разделам.

        Это позволяет не потерять другие права пользователя (например,
        из групп) при изменении доступа к разделам.
        """
        super().save_related(request, form, formsets, change)
        user = form.instance

        # Сохраняем права, не связанные с разделами
        keep = list(user.user_permissions.exclude(codename__startswith="access_"))
        # Устанавливаем полный список прав: старые + новые разделы
        user.user_permissions.set(keep + list(form.cleaned_data.get("sections") or []))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        Profile.objects.update_or_create(
            user=obj,
            defaults={
                "patronymic": form.cleaned_data.get("patronymic", ""),
                "api_key": form.cleaned_data.get("api_key", ""),
                "is_fired": form.cleaned_data.get("is_fired", ""),
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

    def fetch_external_data(self, request, tab_number):
        api_key = getattr(getattr(request.user, "profile", None), "api_key", None)
        if not api_key:
            return JsonResponse(
                {"error": "У текущего пользователя не задан API ключ"}, status=400
            )

        url = f"{API_PATH}{tab_number}/"

        try:
            response = requests.get(
                url,
                params={"api_key": api_key},
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            return JsonResponse({"error": f"Ошибка обращения к API: {e}"}, status=502)

        try:
            data = response.json()
        except ValueError:
            return JsonResponse({"error": "Некорректный ответ от API"}, status=502)

        result = {
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

        return JsonResponse(result)
