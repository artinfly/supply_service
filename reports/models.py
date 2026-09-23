"""
Модели данных приложения reports.

Основные таблицы:
- igk_stat_data: позиции договоров (рабочая)
- znp_data / znp_data_sap: заявки на платёж (рабочие)
- staging_*: временные таблицы для импорта Excel
- contracts_history: история изменений договоров
- contract_counts_snapshot: снимки количества договоров
- contracts_appeared: журнал появившихся договоров
- nsi_igk: справочник ИГК
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models

# --- Справочники ---


class NsiIgk(models.Model):
    """Справочник ИГК — используется для выпадающих списков на сводках."""

    igk_id = models.AutoField(primary_key=True, verbose_name="ID записи")
    igk = models.CharField(max_length=50, unique=True, verbose_name="Код ИГК")

    class Meta:
        db_table = "nsi_igk"
        verbose_name = "Справочник ИГК"
        verbose_name_plural = "Справочник ИГК"

    def __str__(self):
        return self.igk


class GozContractVat(models.Model):
    """
    Справочник ГК для анализа отчётов ЕИС ГОЗ — ставка НДС по контракту.
    У контрактов разных лет ставка НДС может отличаться, но для одного
    и того же ГК она всегда одна.
    """

    igk = models.CharField(max_length=10, unique=True, verbose_name="ГК")
    vat_rate = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("20.0"),
        verbose_name="Ставка НДС, %",
    )

    class Meta:
        db_table = "goz_contract_vat"
        verbose_name = "ГК (ставка НДС)"
        verbose_name_plural = "Анализ ГОЗ: справочник ставок НДС"
        ordering = ["igk"]

    def __str__(self):
        return f"{self.igk} — {self.vat_rate}%"


# --- Основные рабочие таблицы ---


class IgkStatData(models.Model):
    """
    Позиция договора — основная рабочая таблица.
    Полностью перезаписывается при каждой загрузке файла договоров.
    """

    pp_id = models.AutoField(primary_key=True, verbose_name="Внутренний ID")
    igk = models.CharField(max_length=500, null=True, verbose_name="Код ИГК")
    c_agent = models.CharField(max_length=500, null=True, verbose_name="Контрагент")
    cfo = models.CharField(max_length=500, null=True, verbose_name="ЦФО")
    contract = models.CharField(
        max_length=500, null=True, verbose_name="Номер договора"
    )
    status = models.CharField(max_length=500, null=True, verbose_name="Статус договора")
    payment_type = models.CharField(
        max_length=500, null=True, verbose_name="Тип платежа"
    )
    item = models.CharField(max_length=500, null=True, verbose_name="Предмет договора")
    # Зарезервированное слово в SQL, экранируем через db_column
    order = models.CharField(
        max_length=500, null=True, db_column="order", verbose_name="Номер заказа"
    )

    # Финансовые данные: используем Decimal для точности
    plan = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Плановая сумма"
    )
    fact = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Фактическая сумма"
    )
    remainder = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Остаток"
    )
    tolerance = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, verbose_name="Допуск (%)"
    )
    contract_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Сумма всего договора"
    )

    stage = models.CharField(max_length=250, null=True, verbose_name="Этап графика")

    # Флаги годов ИГК
    y25 = models.BooleanField(null=True, verbose_name="Флаг 2025 года")
    y26 = models.BooleanField(null=True, verbose_name="Флаг 2026 года")
    y27 = models.BooleanField(null=True, verbose_name="Флаг 2027 года")

    plan_date = models.CharField(
        max_length=50, null=True, verbose_name="Плановая дата (строка)"
    )
    c_date = models.CharField(
        max_length=256, null=True, verbose_name="Дата заключения (строка)"
    )

    crc32_hash = models.BigIntegerField(verbose_name="CRC32 хеш для привязки")

    class Meta:
        db_table = "igk_stat_data"
        verbose_name = "Позиция договора"
        verbose_name_plural = "Позиции договоров"
        indexes = [
            models.Index(fields=["crc32_hash"], name="idx_igk_crc32"),
            models.Index(fields=["igk"], name="idx_igk_code"),
            models.Index(fields=["cfo"], name="idx_igk_cfo"),
            models.Index(fields=["status"], name="idx_igk_status"),
            models.Index(fields=["payment_type"], name="idx_igk_payment"),
        ]

    def __str__(self):
        return f"{self.igk} / {self.contract}"


# --- Staging таблицы (импорт) ---


class StagingExcel(models.Model):
    """Временная таблица для импорта договоров (строки как есть)."""

    id = models.AutoField(primary_key=True)
    igk = models.TextField(null=True, verbose_name="ИГК")
    kontragent = models.TextField(null=True, verbose_name="Контрагент")
    cfo = models.TextField(null=True, verbose_name="ЦФО")
    dogovor = models.TextField(null=True, verbose_name="Договор")
    sostoyanie = models.TextField(null=True, verbose_name="Состояние")
    tip_platezha = models.TextField(null=True, verbose_name="Тип платежа")
    predmet = models.TextField(null=True, verbose_name="Предмет")
    zakaz = models.TextField(null=True, verbose_name="Заказ")
    plan = models.TextField(null=True, verbose_name="План")
    fakt = models.TextField(null=True, verbose_name="Факт")
    ostatok = models.TextField(null=True, verbose_name="Остаток")
    tol = models.TextField(null=True, verbose_name="Допуск")
    etap_grafika = models.TextField(null=True, verbose_name="Этап графика")
    dataplan = models.TextField(null=True, verbose_name="Дата план")
    summa_dogovora = models.TextField(null=True, verbose_name="Сумма договора")
    god_igk = models.TextField(null=True, verbose_name="Год ИГК")

    class Meta:
        db_table = "staging_excel"
        verbose_name = "Строка импорта договоров"
        verbose_name_plural = "Строки импорта договоров"

    def __str__(self):
        return f"Staging: {self.igk} / {self.dogovor}"


class StagingZnpExcel(models.Model):
    """Временная таблица для импорта заявок ФЗД."""

    id = models.AutoField(primary_key=True)
    igk = models.TextField(null=True, verbose_name="ИГК")
    znp_igk = models.TextField(null=True, verbose_name="ИГК заявки")
    znp_payment_type = models.CharField(
        max_length=100, null=True, verbose_name="Тип платежа заявки"
    )
    c_agent = models.TextField(null=True, verbose_name="Контрагент")
    contract = models.TextField(null=True, verbose_name="Договор")
    stage = models.TextField(null=True, verbose_name="Этап")
    plan_doc = models.TextField(null=True, verbose_name="Плановый документ")
    payment_purpose = models.TextField(null=True, verbose_name="Назначение платежа")
    plan_payment_date = models.TextField(null=True, verbose_name="Плановая дата")
    fact_payment_date = models.TextField(null=True, verbose_name="Фактическая дата")
    plan_sum = models.FloatField(null=True, verbose_name="Плановая сумма")
    fact_sum = models.FloatField(null=True, verbose_name="Фактическая сумма")
    znp_status = models.TextField(null=True, verbose_name="Статус заявки")
    znp_date = models.TextField(null=True, verbose_name="Дата заявки")
    crc32_hash = models.BigIntegerField(verbose_name="CRC32 хеш для привязки")

    class Meta:
        db_table = "staging_znp_excel"
        verbose_name = "Строка импорта ЗнП (ФЗД)"
        verbose_name_plural = "Строки импорта ЗнП (ФЗД)"

    def __str__(self):
        return f"Staging ЗнП: {self.plan_doc}"


class ZnpData(models.Model):
    """Рабочая таблица заявок на платёж ФЗД."""

    id = models.AutoField(primary_key=True)

    parent = models.ForeignKey(
        IgkStatData,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        verbose_name="Родительская позиция договора",
    )
    crc32_hash = models.BigIntegerField(null=True, verbose_name="CRC32 хеш")

    stage = models.CharField(max_length=250, null=True, verbose_name="Этап")
    plan_doc = models.CharField(
        max_length=255, null=True, verbose_name="Плановый документ"
    )
    payment_purpose = models.CharField(
        max_length=500, null=True, verbose_name="Назначение платежа"
    )
    plan_payment_date = models.DateField(
        null=True, verbose_name="Плановая дата платежа"
    )
    fact_payment_date = models.DateField(
        null=True, verbose_name="Фактическая дата платежа"
    )
    plan_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Плановая сумма"
    )
    fact_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Фактическая сумма"
    )
    znp_igk = models.TextField(null=True, verbose_name="ИГК заявки")
    znp_payment_type = models.CharField(
        max_length=100, null=True, verbose_name="Тип платежа"
    )
    znp_status = models.CharField(
        max_length=100, null=True, verbose_name="Статус заявки"
    )
    znp_date = models.DateField(null=True, verbose_name="Дата заявки")

    class Meta:
        db_table = "znp_data"
        verbose_name = "Заявка на платёж (ФЗД)"
        verbose_name_plural = "Заявки на платёж (ФЗД)"
        indexes = [
            models.Index(fields=["crc32_hash"], name="idx_znp_crc32"),
            models.Index(fields=["parent_id"], name="idx_znp_parent"),
        ]

    def __str__(self):
        return f"ЗнП: {self.plan_doc}"


class ZnpDataSAP(models.Model):
    """Рабочая таблица заявок на платёж SAP."""

    id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=500, null=True, verbose_name="ИГК")
    cfo = models.CharField(max_length=4, null=True, verbose_name="ЦФО")
    c_agent = models.CharField(max_length=500, verbose_name="Контрагент")
    reg_num = models.CharField(max_length=255, null=True, verbose_name="Рег. номер")
    items = models.CharField(max_length=500, null=True, verbose_name="Предметы")
    vv_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Сумма ВВ"
    )
    bank_name = models.CharField(max_length=500, null=True, verbose_name="Банк")

    stage_e = models.DateField(null=True, verbose_name="Этап E")
    stage_f = models.DateField(null=True, verbose_name="Этап F")
    payment_possible = models.DateField(
        null=True, verbose_name="Возможная дата платежа"
    )
    init_payment_date = models.DateField(
        null=True, verbose_name="Изначальная дата платежа"
    )
    normalize_doc_num = models.CharField(
        max_length=255, null=True, verbose_name="Нормализованный номер"
    )

    class Meta:
        db_table = "znp_data_sap"
        verbose_name = "Заявка на платёж (SAP)"
        verbose_name_plural = "Заявки на платёж (SAP)"
        indexes = [
            models.Index(fields=["cfo"], name="idx_sap_cfo"),
            models.Index(fields=["igk"], name="idx_sap_igk"),
        ]

    def __str__(self):
        return f"ЗнП SAP: {self.reg_num}"


class StagingZnpSAPExcel(models.Model):
    """Временная таблица для импорта заявок SAP."""

    id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=500, null=True, verbose_name="ИГК")
    cfo = models.CharField(max_length=4, verbose_name="ЦФО")
    c_agent = models.CharField(max_length=500, verbose_name="Контрагент")
    reg_num = models.CharField(max_length=255, null=True, verbose_name="Рег. номер")
    items = models.CharField(max_length=500, null=True, verbose_name="Предметы")
    vv_sum = models.FloatField(null=True, verbose_name="Сумма ВВ")
    bank_name = models.CharField(max_length=500, null=True, verbose_name="Банк")
    c_type = models.CharField(max_length=50, verbose_name="Тип")

    stage_e = models.DateField(null=True, verbose_name="Этап E")
    stage_f = models.DateField(null=True, verbose_name="Этап F")
    payment_possible = models.DateField(
        null=True, verbose_name="Возможная дата платежа"
    )
    init_payment_date = models.DateField(
        null=True, verbose_name="Изначальная дата платежа"
    )
    normalize_doc_num = models.CharField(
        max_length=255, null=True, verbose_name="Нормализованный номер"
    )

    class Meta:
        db_table = "staging_znp_sap_excel"
        verbose_name = "Строка импорта ЗнП (SAP)"
        verbose_name_plural = "Строки импорта ЗнП (SAP)"

    def __str__(self):
        return f"Staging ЗнП SAP: {self.reg_num}"


# --- История изменений и снимки ---


class ContractsHistory(models.Model):
    """История изменений договоров (статус, план, факт)."""

    id = models.AutoField(primary_key=True)
    hash = models.BinaryField(verbose_name="MD5 хеш позиции")

    old_status = models.CharField(
        max_length=500, null=True, verbose_name="Старый статус"
    )
    new_status = models.CharField(
        max_length=500, null=True, verbose_name="Новый статус"
    )

    update_date = models.DateField(null=True, verbose_name="Дата изменения в файле")
    upload_date = models.DateField(null=True, verbose_name="Дата загрузки в систему")

    old_plan = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Старый план"
    )
    new_plan = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Новый план"
    )

    old_fact = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Старый факт"
    )
    new_fact = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Новый факт"
    )

    plan_changed_date = models.DateField(null=True, verbose_name="Дата изменения плана")
    fact_changed_date = models.DateField(null=True, verbose_name="Дата изменения факта")

    old_contract_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Старая сумма договора"
    )
    new_contract_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Новая сумма договора"
    )

    class Meta:
        db_table = "contracts_history"
        verbose_name = "Изменение договора"
        verbose_name_plural = "Изменения договоров"
        indexes = [
            models.Index(fields=["hash"], name="idx_history_hash"),
        ]

    def __str__(self):
        return f"Изменение #{self.id}"


class ContractCountsSnapshot(models.Model):
    """Снимок количества заключённых договоров на дату загрузки."""

    id = models.AutoField(primary_key=True)
    upload_date = models.DateField(verbose_name="Дата загрузки (снимка)")
    igk = models.CharField(max_length=10, verbose_name="Код ИГК")
    cfo = models.CharField(max_length=500, verbose_name="ЦФО")
    year_col = models.CharField(max_length=5, verbose_name="Колонка года (y25, y26...)")
    concluded_count = models.IntegerField(
        default=0, verbose_name="Количество заключённых"
    )

    class Meta:
        db_table = "contract_counts_snapshot"
        verbose_name = "Снимок количества договоров"
        verbose_name_plural = "Снимки количества договоров"
        constraints = [
            models.UniqueConstraint(
                fields=["upload_date", "igk", "cfo", "year_col"],
                name="contract_counts_snapshot_unique_key",
            )
        ]

    def __str__(self):
        return f"{self.igk}/{self.cfo} {self.year_col} — {self.concluded_count} на {self.upload_date}"


class ContractsAppeared(models.Model):
    """Журнал появившихся договоров."""

    id = models.AutoField(primary_key=True)
    upload_date = models.DateField(verbose_name="Дата загрузки")
    kind = models.CharField(max_length=20, verbose_name="Тип появления")
    reason = models.CharField(max_length=20, verbose_name="Причина")

    igk = models.CharField(max_length=500, null=True, verbose_name="ИГК")
    cfo = models.CharField(max_length=500, null=True, verbose_name="ЦФО")
    c_agent = models.CharField(max_length=500, null=True, verbose_name="Контрагент")
    contract = models.CharField(max_length=500, null=True, verbose_name="Договор")
    item = models.CharField(max_length=500, null=True, verbose_name="Предмет")
    order_num = models.CharField(max_length=500, null=True, verbose_name="Номер заказа")
    stage = models.CharField(max_length=500, null=True, verbose_name="Этап")
    plan_date = models.CharField(max_length=20, null=True, verbose_name="Плановая дата")
    status = models.CharField(max_length=500, null=True, verbose_name="Статус")
    plan = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="План"
    )
    contract_sum = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, verbose_name="Сумма договора"
    )

    class Meta:
        db_table = "contracts_appeared"
        verbose_name = "Появившийся договор"
        verbose_name_plural = "Появившиеся договоры"
        indexes = [
            models.Index(fields=["upload_date", "kind"], name="idx_appeared_date_kind"),
        ]

    def __str__(self):
        return f"{self.contract} - {self.kind} на {self.upload_date}"


# --- Права доступа и системные данные ---


class Access(models.Model):
    """Модель-заглушка для кастомных прав доступа (таблица в БД не создаётся)."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("access_dashboard", "Раздел: Договорная работа"),
            ("access_znp", "Раздел: ЗнП (ФЗД)"),
            ("access_znp_sap", "Раздел: ЗнП (SAP)"),
            ("access_kdr", "Раздел: КДР по годам"),
            ("access_igk", "Раздел: ИГК по годам"),
            ("access_history", "Раздел: История изменений"),
            ("access_dupes", "Раздел: Дубликаты"),
            ("access_export", "Раздел: Отчёты в Excel"),
            ("access_upload", "Раздел: Загрузка данных"),
            ("access_goz_report", "Раздел: Анализ ГОЗ"),
        ]


class SystemEvent(models.Model):
    """Системные события для отслеживания времени последней загрузки."""

    id = models.AutoField(primary_key=True)
    event_key = models.CharField(
        max_length=50, unique=True, verbose_name="Ключ события"
    )
    event_time = models.DateTimeField(verbose_name="Время события")

    class Meta:
        db_table = "system_events"
        verbose_name = "Системное событие"
        verbose_name_plural = "Системные события"

    def __str__(self):
        return f"{self.event_key} — {self.event_time}"


class Profile(models.Model):
    """Расширенный профиль пользователя с данными из HR-системы."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Пользователь",
    )
    api_key = models.CharField(
        max_length=64, blank=True, null=True, verbose_name="API ключ"
    )
    patronymic = models.CharField(max_length=255, blank=True, verbose_name="Отчество")
    is_fired = models.BooleanField(default=False, verbose_name="Уволен?")

    last_synced_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Последняя синхронизация"
    )
    sync_error = models.TextField(
        blank=True, verbose_name="Ошибка последней синхронизации"
    )

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self):
        return f"Профиль: {self.user.username}"
