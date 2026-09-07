"""
Модели данных приложения reports.

Основные таблицы:
- igk_stat_data: позиции договоров (рабочая)
- znp_data: заявки на платёж ФЗД (рабочая)
- znp_data_sap: заявки на платёж SAP (рабочая)
- staging_*: временные таблицы для импорта Excel
- contracts_history: история изменений договоров
- contract_counts_snapshot: снимки количества договоров по датам
- contracts_appeared: журнал появившихся договоров
- nsi_igk: справочник ИГК для фильтров на страницах
- SystemEvent: системные события (время последней загрузки)
- Profile: дополнительная информация о пользователе (отчество, API-ключ и т.д.)
"""

from django.contrib.auth.models import User
from django.db import models


class NsiIgk(models.Model):
    """
    Справочник ИГК — используется для выпадающих списков на сводках.
    Заполняется при загрузке договоров, значения берутся из колонки «ИГК».
    """

    igk_id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=50, unique=True)

    class Meta:
        managed = True
        db_table = "nsi_igk"
        verbose_name = "ИГК"
        verbose_name_plural = "ИГК"

    def __str__(self):
        return self.igk


# ============================================================================
# Основные рабочие таблицы
# ============================================================================


class IgkStatData(models.Model):
    """
    Позиция договора — основная рабочая таблица.

    Каждая строка представляет одну позицию (этап графика) договора.
    Полностью перезаписывается при каждой загрузке файла договоров.

    ВАЖНО: pp_id и id меняются после каждой загрузки и не могут служить
    внешними ссылками. Для привязки заявок используется crc32_hash.
    """

    pp_id = models.AutoField(primary_key=True)

    igk = models.CharField(max_length=500, null=True)
    c_agent = models.CharField(max_length=500, null=True)
    cfo = models.CharField(max_length=500, null=True)
    contract = models.CharField(max_length=500, null=True)
    status = models.CharField(max_length=500, null=True)
    payment_type = models.CharField(max_length=500, null=True)
    item = models.CharField(max_length=500, null=True)
    order = models.CharField(max_length=500, null=True, db_column='"order"')

    plan = models.FloatField(null=True)
    fact = models.FloatField(null=True)
    remainder = models.FloatField(null=True)
    tolerance = models.FloatField(null=True)

    stage = models.CharField(max_length=250, null=True)

    # Флаги годов ИГК
    y25 = models.BooleanField(null=True)
    y26 = models.BooleanField(null=True)
    y27 = models.BooleanField(null=True)

    plan_date = models.CharField(max_length=50, null=True)
    c_date = models.CharField(max_length=256, null=True)
    contract_sum = models.FloatField(null=True)

    # CRC32-хеш для привязки заявок
    crc32_hash = models.BigIntegerField()

    class Meta:
        managed = True
        db_table = "igk_stat_data"
        verbose_name = "Позиция договора"
        verbose_name_plural = "Позиции договоров"
        indexes = [
            models.Index(fields=["crc32_hash"]),
            models.Index(fields=["igk"]),
            models.Index(fields=["cfo"]),
            models.Index(fields=["status"]),
            models.Index(fields=["payment_type"]),
        ]

    def __str__(self):
        return f"{self.igk} / {self.contract}"


# ============================================================================
# Staging таблицы (временные, для импорта Excel)
# ============================================================================


class StagingExcel(models.Model):
    """
    Staging таблица для импорта договоров.
    Все поля — TextField, чтобы не было ошибок парсинга при загрузке.
    """

    id = models.AutoField(primary_key=True)

    igk = models.TextField(null=True)
    kontragent = models.TextField(null=True)
    cfo = models.TextField(null=True)
    dogovor = models.TextField(null=True)
    sostoyanie = models.TextField(null=True)
    tip_platezha = models.TextField(null=True)
    predmet = models.TextField(null=True)
    zakaz = models.TextField(null=True)
    plan = models.TextField(null=True)
    fakt = models.TextField(null=True)
    ostatok = models.TextField(null=True)
    tol = models.TextField(null=True)
    etap_grafika = models.TextField(null=True)
    dataplan = models.TextField(null=True)
    summa_dogovora = models.TextField(null=True)
    god_igk = models.TextField(null=True)

    class Meta:
        managed = True
        db_table = "staging_excel"
        verbose_name = "Строка импорта"
        verbose_name_plural = "Строки импорта"

    def __str__(self):
        return f"{self.igk} / {self.dogovor}"


class StagingZnpExcel(models.Model):
    """
    Staging таблица для импорта заявок ФЗД.
    """

    id = models.AutoField(primary_key=True)

    igk = models.TextField(null=True)
    znp_igk = models.TextField(null=True)
    znp_payment_type = models.CharField(max_length=50, null=True)
    c_agent = models.TextField(null=True)
    contract = models.TextField(null=True)
    stage = models.TextField(null=True)
    plan_doc = models.TextField(null=True)
    payment_purpose = models.TextField(null=True)
    plan_payment_date = models.TextField(null=True)
    fact_payment_date = models.TextField(null=True)
    plan_sum = models.FloatField(null=True)
    fact_sum = models.FloatField(null=True)
    znp_status = models.TextField(null=True)
    znp_date = models.TextField(null=True)

    crc32_hash = models.BigIntegerField(null=False)

    class Meta:
        managed = True
        db_table = "staging_znp_excel"
        verbose_name = "Строка импорта ЗнП"
        verbose_name_plural = "Строки импорта ЗнП"

    def __str__(self):
        return f"{self.plan_doc}"


class ZnpData(models.Model):
    """
    Заявка на платёж ФЗД — основная рабочая таблица.
    """

    id = models.AutoField(primary_key=True)

    parent = models.ForeignKey(
        IgkStatData,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )
    crc32_hash = models.BigIntegerField(null=True)

    stage = models.CharField(max_length=250, null=True)
    plan_doc = models.CharField(max_length=255, null=True)
    payment_purpose = models.CharField(max_length=255, null=True)
    plan_payment_date = models.DateField(null=True)
    fact_payment_date = models.DateField(null=True)
    plan_sum = models.FloatField(null=True)
    fact_sum = models.FloatField(null=True)
    znp_igk = models.TextField(null=True)
    znp_payment_type = models.CharField(max_length=50, null=True)
    znp_status = models.CharField(max_length=100, null=True)
    znp_date = models.DateField(null=True)

    class Meta:
        managed = True
        db_table = "znp_data"
        verbose_name = "Заявка на платёж"
        verbose_name_plural = "Заявки на платёж"
        indexes = [models.Index(fields=["crc32_hash"])]

    def __str__(self):
        return f"{self.plan_doc}"


class ZnpDataSAP(models.Model):
    """
    Заявка на платёж SAP — рабочая таблица для заявок из SAP.
    """

    id = models.AutoField(primary_key=True)

    igk = models.CharField(max_length=50, null=True)
    cfo = models.CharField(max_length=4, null=True)
    c_agent = models.CharField(max_length=255)  # обязательное поле
    reg_num = models.CharField(max_length=100, null=True)
    items = models.CharField(max_length=500, null=True)
    vv_sum = models.FloatField(null=True)
    bank_name = models.CharField(max_length=255, null=True)

    stage_e = models.DateField(null=True)
    stage_f = models.DateField(null=True)
    payment_possible = models.DateField(null=True)
    init_payment_date = models.DateField(null=True)
    normalize_doc_num = models.CharField(max_length=100, null=True)

    class Meta:
        managed = True
        db_table = "znp_data_sap"
        verbose_name = "Заявка на платёж(САП)"
        verbose_name_plural = "Заявки на платёж(САП)"
        indexes = [
            models.Index(fields=["cfo"]),
            models.Index(fields=["igk"]),
        ]

    def __str__(self):
        return f"{self.reg_num}"


class StagingZnpSAPExcel(models.Model):
    """
    Staging таблица для импорта заявок SAP.
    """

    id = models.AutoField(primary_key=True)

    igk = models.CharField(max_length=50, null=True)
    cfo = models.CharField(max_length=4)
    c_agent = models.CharField(max_length=255)
    reg_num = models.CharField(max_length=100, null=True)
    items = models.CharField(max_length=500, null=True)
    vv_sum = models.FloatField(null=True)
    bank_name = models.CharField(max_length=255, null=True)
    c_type = models.CharField(max_length=50)
    stage_e = models.DateField(null=True)
    stage_f = models.DateField(null=True)
    payment_possible = models.DateField(null=True)
    init_payment_date = models.DateField(null=True)
    normalize_doc_num = models.CharField(max_length=100, null=True)

    class Meta:
        managed = True
        db_table = "staging_znp_sap_excel"
        verbose_name = "Строка импорта ЗнП(САП)"
        verbose_name_plural = "Строки импорта ЗнП(САП)"

    def __str__(self):
        return f"{self.reg_num}"


# ============================================================================
# История изменений и снимки
# ============================================================================


class ContractsHistory(models.Model):
    """
    История изменений договоров.
    Поле hash — бинарный хеш позиции договора (через pgcrypto.digest).
    """

    id = models.AutoField(primary_key=True)

    hash = models.BinaryField()

    old_status = models.CharField(max_length=500, null=True)
    new_status = models.CharField(max_length=500, null=True)

    update_date = models.DateField(null=True)
    upload_date = models.DateField(null=True)

    old_plan = models.FloatField(null=True)
    new_plan = models.FloatField(null=True)

    old_fact = models.FloatField(null=True)
    new_fact = models.FloatField(null=True)

    plan_changed_date = models.DateField(null=True)
    fact_changed_date = models.DateField(null=True)

    old_contract_sum = models.FloatField(null=True)
    new_contract_sum = models.FloatField(null=True)

    class Meta:
        managed = True
        db_table = "contracts_history"
        verbose_name = "Изменение договора"
        verbose_name_plural = "Изменения договоров"
        indexes = [models.Index(fields=["hash"])]

    def __str__(self):
        return f"Изменение #{self.id}"


class ContractCountsSnapshot(models.Model):
    """
    Снимок количества заключённых договоров на дату загрузки.
    Используется для графиков динамики.
    """

    id = models.AutoField(primary_key=True)

    upload_date = models.DateField()
    igk = models.CharField(max_length=10)
    cfo = models.CharField(max_length=500)
    year_col = models.CharField(max_length=5)
    concluded_count = models.IntegerField(default=0)

    class Meta:
        managed = True
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
    """
    Журнал появившихся договоров (новые или изменившие статус).
    """

    id = models.AutoField(primary_key=True)

    upload_date = models.DateField()
    kind = models.CharField(max_length=20)
    reason = models.CharField(max_length=20)

    igk = models.CharField(max_length=500, null=True)
    cfo = models.CharField(max_length=500, null=True)
    c_agent = models.CharField(max_length=500, null=True)
    contract = models.CharField(max_length=500, null=True)
    item = models.CharField(max_length=500, null=True)
    order_num = models.CharField(max_length=500, null=True)
    stage = models.CharField(max_length=500, null=True)
    plan_date = models.CharField(max_length=20, null=True)
    status = models.CharField(max_length=500, null=True)
    plan = models.FloatField(null=True)
    contract_sum = models.FloatField(null=True)

    class Meta:
        managed = True
        db_table = "contracts_appeared"
        verbose_name = "Появившийся договор"
        verbose_name_plural = "Появившиеся договоры"
        indexes = [models.Index(fields=["upload_date", "kind"])]

    def __str__(self):
        return f"{self.contract} - {self.kind} на {self.upload_date}"


# ============================================================================
# Права доступа
# ============================================================================


class Access(models.Model):
    """
    Модель для определения прав доступа к разделам.
    Таблицы в базе НЕТ (managed = False).
    """

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
        ]


# ============================================================================
# Системные события и профили пользователей
# ============================================================================


class SystemEvent(models.Model):
    """
    Системные события — для отслеживания времени последней загрузки.
    Ключ события уникален, например: «last_contracts_upload».
    """

    id = models.AutoField(primary_key=True)

    event_key = models.CharField(max_length=50, unique=True)
    event_time = models.DateTimeField()

    class Meta:
        managed = True
        db_table = "system_events"
        verbose_name = "Системные события"
        verbose_name_plural = "Системные события"

    def __str__(self):
        return f"{self.event_key}-{self.event_time}"


class Profile(models.Model):
    """
    Дополнительная информация о пользователе.
    Расширяет стандартную модель User через OneToOneField.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    # API-ключ для внешних интеграций
    api_key = models.CharField("API ключ", max_length=64, blank=True, null=True)

    # Отчество пользователя
    patronymic = models.CharField("Отчество", max_length=255, blank=True)

    # Признак увольнения (для отключения доступа)
    is_fired = models.BooleanField("Уволен?", default=False)

    # Время последней синхронизации с внешней системой (если используется)
    last_synced_at = models.DateTimeField(
        "Последняя синхронизация", null=True, blank=True
    )

    # Текст ошибки последней синхронизации
    sync_error = models.TextField("Ошибка последней синхронизации", blank=True)

    class Meta:
        managed = True
        db_table = "reports_profile"
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self):
        return f"Profile({self.user.username})"
