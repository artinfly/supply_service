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
"""

from django.contrib.auth.models import User
from django.db import models

# ============================================================================
# Справочники
# ============================================================================


class NsiIgk(models.Model):
    """
    Справочник ИГК — используется для выпадающих списков на сводках.
    Заполняется при загрузке договоров, значения берутся из колонки «ИГК».
    """

    igk_id = models.AutoField(primary_key=True, verbose_name="ID записи")
    igk = models.CharField(max_length=50, unique=True, verbose_name="Код ИГК")

    class Meta:
        managed = True
        db_table = "nsi_igk"
        verbose_name = "Справочник ИГК"
        verbose_name_plural = "Справочник ИГК"

    def __str__(self):
        return self.igk


# ============================================================================
# Основные рабочие таблицы
# ============================================================================


class IgkStatData(models.Model):
    """
    Позиция договора — основная рабочая таблица.
    Полностью перезаписывается при каждой загрузке файла договоров.
    ВАЖНО: pp_id меняется после каждой загрузки и не может служить внешней ссылкой.
    Для привязки заявок используется crc32_hash.
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
    # order — зарезервированное слово SQL, Django сам его экранирует через db_column="order"
    order = models.CharField(
        max_length=500, null=True, db_column="order", verbose_name="Номер заказа"
    )

    plan = models.FloatField(null=True, verbose_name="Плановая сумма")
    fact = models.FloatField(null=True, verbose_name="Фактическая сумма")
    remainder = models.FloatField(null=True, verbose_name="Остаток")
    tolerance = models.FloatField(null=True, verbose_name="Допуск (%)")
    stage = models.CharField(max_length=250, null=True, verbose_name="Этап графика")

    # Флаги годов ИГК (заполняются из колонки «ГодИГК» файла договоров)
    y25 = models.BooleanField(null=True, verbose_name="Флаг 2025 года")
    y26 = models.BooleanField(null=True, verbose_name="Флаг 2026 года")
    y27 = models.BooleanField(null=True, verbose_name="Флаг 2027 года")

    plan_date = models.CharField(
        max_length=50, null=True, verbose_name="Плановая дата (строка)"
    )
    c_date = models.CharField(
        max_length=256, null=True, verbose_name="Дата заключения (строка)"
    )
    contract_sum = models.FloatField(null=True, verbose_name="Сумма всего договора")

    # CRC32-хеш от (ИГК + контрагент + договор + этап). При изменении любого поля привязка теряется.
    crc32_hash = models.BigIntegerField(verbose_name="CRC32 хеш для привязки")

    class Meta:
        managed = True
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


# ============================================================================
# Staging таблицы (временные, для импорта Excel)
# ============================================================================


class StagingExcel(models.Model):
    """
    Временная таблица для импорта договоров.
    Записывает строки Excel «как есть» (всё в TextField) для избежания ошибок парсинга.
    Конвертация типов происходит в services/normalize.py. Очищается при каждой загрузке.
    """

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
        managed = True
        db_table = "staging_excel"
        verbose_name = "Строка импорта договоров"
        verbose_name_plural = "Строки импорта договоров"

    def __str__(self):
        return f"Staging: {self.igk} / {self.dogovor}"


class StagingZnpExcel(models.Model):
    """
    Временная таблица для импорта заявок ФЗД.
    Записывает строки Excel «как есть». Очищается при каждой загрузке.
    """

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
    crc32_hash = models.BigIntegerField(
        null=False, verbose_name="CRC32 хеш для привязки"
    )

    class Meta:
        managed = True
        db_table = "staging_znp_excel"
        verbose_name = "Строка импорта ЗнП (ФЗД)"
        verbose_name_plural = "Строки импорта ЗнП (ФЗД)"

    def __str__(self):
        return f"Staging ЗнП: {self.plan_doc}"


class ZnpData(models.Model):
    """
    Рабочая таблица заявок на платёж ФЗД.
    Привязывается к позиции договора через parent (ForeignKey) и crc32_hash.
    Если crc32_hash не совпадает ни с одной позицией, parent = NULL, и заявка скрыта из выборок.
    """

    id = models.AutoField(primary_key=True)

    # db_constraint=False, так как таблица полностью перезаписывается при загрузке
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
    plan_sum = models.FloatField(null=True, verbose_name="Плановая сумма")
    fact_sum = models.FloatField(null=True, verbose_name="Фактическая сумма")
    znp_igk = models.TextField(null=True, verbose_name="ИГК заявки")
    znp_payment_type = models.CharField(
        max_length=100, null=True, verbose_name="Тип платежа"
    )
    znp_status = models.CharField(
        max_length=100, null=True, verbose_name="Статус заявки"
    )
    znp_date = models.DateField(null=True, verbose_name="Дата заявки")

    class Meta:
        managed = True
        db_table = "znp_data"
        verbose_name = "Заявка на платёж (ФЗД)"
        verbose_name_plural = "Заявки на платёж (ФЗД)"
        indexes = [
            models.Index(fields=["crc32_hash"], name="idx_znp_crc32"),
        ]

    def __str__(self):
        return f"ЗнП: {self.plan_doc}"


class ZnpDataSAP(models.Model):
    """
    Рабочая таблица заявок на платёж SAP.
    Отдельная таблица из-за отличий в структуре. Статус вычисляется по датам этапов.
    """

    id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=500, null=True, verbose_name="ИГК")
    cfo = models.CharField(max_length=4, null=True, verbose_name="ЦФО")
    c_agent = models.CharField(max_length=500, verbose_name="Контрагент")
    reg_num = models.CharField(max_length=255, null=True, verbose_name="Рег. номер")
    items = models.CharField(max_length=500, null=True, verbose_name="Предметы")
    vv_sum = models.FloatField(null=True, verbose_name="Сумма ВВ")
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
        managed = True
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
    """
    Временная таблица для импорта заявок SAP. Очищается при каждой загрузке.
    """

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
        managed = True
        db_table = "staging_znp_sap_excel"
        verbose_name = "Строка импорта ЗнП (SAP)"
        verbose_name_plural = "Строки импорта ЗнП (SAP)"

    def __str__(self):
        return f"Staging ЗнП SAP: {self.reg_num}"


# ============================================================================
# История изменений и снимки
# ============================================================================


class ContractsHistory(models.Model):
    """
    История изменений договоров.
    Записывается при загрузке, если изменился статус, план, факт или сумма договора.
    Поле hash — бинарный MD5-хеш позиции для поиска «той же» записи в разных загрузках.
    """

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

    old_plan = models.FloatField(null=True, verbose_name="Старый план")
    new_plan = models.FloatField(null=True, verbose_name="Новый план")

    old_fact = models.FloatField(null=True, verbose_name="Старый факт")
    new_fact = models.FloatField(null=True, verbose_name="Новый факт")

    plan_changed_date = models.DateField(null=True, verbose_name="Дата изменения плана")
    fact_changed_date = models.DateField(null=True, verbose_name="Дата изменения факта")

    old_contract_sum = models.FloatField(
        null=True, verbose_name="Старая сумма договора"
    )
    new_contract_sum = models.FloatField(null=True, verbose_name="Новая сумма договора")

    class Meta:
        managed = True
        db_table = "contracts_history"
        verbose_name = "Изменение договора"
        verbose_name_plural = "Изменения договоров"
        indexes = [
            models.Index(fields=["hash"], name="idx_history_hash"),
        ]

    def __str__(self):
        return f"Изменение #{self.id}"


class ContractCountsSnapshot(models.Model):
    """
    Снимок количества заключённых договоров на дату загрузки.
    Используется для графиков «динамика заключения договоров» на dashboard.
    """

    id = models.AutoField(primary_key=True)
    upload_date = models.DateField(verbose_name="Дата загрузки (снимка)")
    igk = models.CharField(max_length=10, verbose_name="Код ИГК")
    cfo = models.CharField(max_length=500, verbose_name="ЦФО")
    year_col = models.CharField(max_length=5, verbose_name="Колонка года (y25, y26...)")
    concluded_count = models.IntegerField(
        default=0, verbose_name="Количество заключённых"
    )

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
    Журнал появившихся договоров.
    Фиксирует договоры, появившиеся впервые или изменившие статус с «не заключён» на «заключён».
    """

    id = models.AutoField(primary_key=True)
    upload_date = models.DateField(verbose_name="Дата загрузки")
    kind = models.CharField(
        max_length=20, verbose_name="Тип появления (новый/изменил статус)"
    )
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
    plan = models.FloatField(null=True, verbose_name="План")
    contract_sum = models.FloatField(null=True, verbose_name="Сумма договора")

    class Meta:
        managed = True
        db_table = "contracts_appeared"
        verbose_name = "Появившийся договор"
        verbose_name_plural = "Появившиеся договоры"
        indexes = [
            models.Index(fields=["upload_date", "kind"], name="idx_appeared_date_kind"),
        ]

    def __str__(self):
        return f"{self.contract} - {self.kind} на {self.upload_date}"


# ============================================================================
# Права доступа и системные события
# ============================================================================


class Access(models.Model):
    """
    Модель-заглушка для определения кастомных прав доступа к разделам.
    Таблица в БД НЕ создаётся (managed = False). Django использует её только
    для регистрации прав в django_content_type и django_permission.
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


class SystemEvent(models.Model):
    """
    Системные события для отслеживания времени последней загрузки данных.
    """

    id = models.AutoField(primary_key=True)
    event_key = models.CharField(
        max_length=50, unique=True, verbose_name="Ключ события"
    )
    event_time = models.DateTimeField(verbose_name="Время события")

    class Meta:
        managed = True
        db_table = "system_events"
        verbose_name = "Системное событие"
        verbose_name_plural = "Системные события"

    def __str__(self):
        return f"{self.event_key} — {self.event_time}"


class Profile(models.Model):
    """
    Расширенный профиль пользователя.
    Содержит дополнительные метаданные и флаги синхронизации с внешними HR-системами.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Пользователь",
    )
    api_key = models.CharField("API ключ", max_length=64, blank=True, null=True)
    patronymic = models.CharField("Отчество", max_length=255, blank=True)
    is_fired = models.BooleanField("Уволен?", default=False)

    last_synced_at = models.DateTimeField(
        "Последняя синхронизация", null=True, blank=True
    )
    sync_error = models.TextField("Ошибка последней синхронизации", blank=True)

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self):
        return f"Профиль: {self.user.username}"
