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

from django.db import models

# ============================================================================
# Справочники и служебные таблицы
# ============================================================================


class NsiIgk(models.Model):
    """
    Справочник ИГК — используется для выпадающих списков на сводках.
    Заполняется при загрузке договоров, значения берутся из колонки «ИГК».
    """

    # Первичный ключ — автоинкремент
    igk_id = models.AutoField(primary_key=True)
    # Код ИГК — уникальное значение из файла договоров
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

    # Первичный ключ — автоинкремент (меняется при каждой загрузке!)
    pp_id = models.AutoField(primary_key=True)

    # Код ИГК (инвестиционно-гражданский комплекс)
    igk = models.CharField(max_length=500, null=True)
    # Контрагент (название организации)
    c_agent = models.CharField(max_length=500, null=True)
    # ЦФО (центр финансовой ответственности)
    cfo = models.CharField(max_length=500, null=True)
    # Номер договора
    contract = models.CharField(max_length=500, null=True)
    # Статус договора: заключён / не заключён / расторгнут
    status = models.CharField(max_length=500, null=True)
    # Тип платежа: аванс / постоплата
    payment_type = models.CharField(max_length=500, null=True)
    # Предмет договора
    item = models.CharField(max_length=500, null=True)
    # Номер заказа — order это зарезервированное слово SQL, поэтому db_column
    order = models.CharField(max_length=500, null=True, db_column='"order"')

    # Плановая сумма позиции
    plan = models.FloatField(null=True)
    # Фактическая сумма (сколько уже оплачено)
    fact = models.FloatField(null=True)
    # Остаток (plan - fact)
    remainder = models.FloatField(null=True)
    # Допуск (порог для определения «нужна ли заявка»)
    tolerance = models.FloatField(null=True)

    # Этап графика платежей
    stage = models.CharField(max_length=250, null=True)

    # Флаги годов ИГК: попадает ли позиция в соответствующий год
    # Заполняются из колонки «ГодИГК» файла договоров
    y25 = models.BooleanField(null=True)  # 2025 год
    y26 = models.BooleanField(null=True)  # 2026 год
    y27 = models.BooleanField(null=True)  # 2027 год

    # Плановая дата оплаты (строка в исходном файле)
    plan_date = models.CharField(max_length=50, null=True)
    # Дата заключения договора (строка в исходном файле)
    c_date = models.CharField(max_length=256, null=True)
    # Сумма всего договора (не позиции!)
    contract_sum = models.FloatField(null=True)

    # CRC32-хеш от четырёх полей: ИГК, контрагент, договор, этап графика
    # Используется для привязки заявок ФЗД к позициям договоров.
    # Если хотя бы одно поле изменилось, привязка теряется.
    crc32_hash = models.BigIntegerField()

    class Meta:
        managed = True
        db_table = "igk_stat_data"
        verbose_name = "Позиция договора"
        verbose_name_plural = "Позиции договоров"
        # Индексы для ускорения поиска и фильтрации
        indexes = [
            models.Index(fields=["crc32_hash"]),  # привязка заявок
            models.Index(fields=["igk"]),  # фильтры по ИГК
            models.Index(fields=["cfo"]),  # фильтры по ЦФО
            models.Index(fields=["status"]),  # фильтры по статусу
            models.Index(fields=["payment_type"]),  # фильтры по типу платежа
        ]

    def __str__(self):
        return f"{self.igk} / {self.contract}"


# ============================================================================
# Staging таблицы (временные, для импорта Excel)
# ============================================================================


class StagingExcel(models.Model):
    """
    Staging таблица для импорта договоров.

    Сюда записываются строки файла Excel «как есть» перед переносом в
    igk_stat_data. Очищается при каждой загрузке.

    Все поля — TextField, чтобы не было ошибок парсинга при загрузке.
    Конвертация в правильные типы происходит в services/normalize.py.
    """

    id = models.AutoField(primary_key=True)

    # Поля соответствуют колонкам файла договоров
    igk = models.TextField(null=True)  # ИГК
    kontragent = models.TextField(null=True)  # Контрагент
    cfo = models.TextField(null=True)  # ЦФО
    dogovor = models.TextField(null=True)  # Номер договора
    sostoyanie = models.TextField(null=True)  # Состояние (статус)
    tip_platezha = models.TextField(null=True)  # Тип платежа
    predmet = models.TextField(null=True)  # Предмет
    zakaz = models.TextField(null=True)  # Заказ
    plan = models.TextField(null=True)  # План
    fakt = models.TextField(null=True)  # Факт
    ostatok = models.TextField(null=True)  # Остаток
    tol = models.TextField(null=True)  # Допуск
    etap_grafika = models.TextField(null=True)  # Этап графика
    dataplan = models.TextField(null=True)  # Плановая дата
    summa_dogovora = models.TextField(null=True)  # Сумма договора
    god_igk = models.TextField(null=True)  # Год ИГК (для флагов y25/y26/y27)

    class Meta:
        managed = True
        db_table = "staging_excel"
        verbose_name = "Строка импорта"
        verbose_name_plural = "Строки импорта"

    def __str__(self):
        return f"{self.igk} / {self.dogovor}"


class StagingZnpExcel(models.Model):
    """
    Staging таблица для импорта заявок ФЗД (финансово-закупочная деятельность).

    Сюда записываются строки файла Excel заявок «как есть».
    После нормализации данные переносятся в znp_data, а crc32_hash
    используется для привязки к позициям договоров.
    """

    id = models.AutoField(primary_key=True)

    # Поля из файла заявок ФЗД
    igk = models.TextField(null=True)  # ИГК
    znp_igk = models.TextField(null=True)  # ИГК заявки
    znp_payment_type = models.CharField(null=True)  # Тип платежа
    c_agent = models.TextField(null=True)  # Контрагент
    contract = models.TextField(null=True)  # Договор
    stage = models.TextField(null=True)  # Этап графика
    plan_doc = models.TextField(null=True)  # Плановый документ
    payment_purpose = models.TextField(null=True)  # Назначение платежа
    plan_payment_date = models.TextField(null=True)  # Плановая дата платежа
    fact_payment_date = models.TextField(null=True)  # Фактическая дата платежа
    plan_sum = models.FloatField(null=True)  # Плановая сумма
    fact_sum = models.FloatField(null=True)  # Фактическая сумма
    znp_status = models.TextField(null=True)  # Статус заявки
    znp_date = models.TextField(null=True)  # Дата заявки

    # CRC32-хеш для привязки к позиции договора (ИГК + контрагент + договор + этап)
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

    Привязывается к позиции договора через parent (ForeignKey) и crc32_hash.
    Если crc32_hash не совпадает ни с одной позицией договора, parent = NULL
    и заявка не попадает ни на одну страницу (все выборки идут через parent).
    """

    id = models.AutoField(primary_key=True)

    # Ссылка на позицию договора (может быть NULL если привязка не удалась)
    # db_constraint=False: таблица полностью перезаписывается при загрузке,
    # поэтому foreign key constraint мешает очистке
    parent = models.ForeignKey(
        IgkStatData,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    # CRC32-хеш для поиска родительской позиции договора
    crc32_hash = models.BigIntegerField(null=True)

    # Поля заявки
    stage = models.CharField(max_length=250, null=True)  # Этап графика
    plan_doc = models.CharField(null=True)  # Плановый документ
    payment_purpose = models.CharField(null=True)  # Назначение платежа
    plan_payment_date = models.DateField(null=True)  # Плановая дата платежа
    fact_payment_date = models.DateField(null=True)  # Фактическая дата
    plan_sum = models.FloatField(null=True)  # Плановая сумма
    fact_sum = models.FloatField(null=True)  # Фактическая сумма
    znp_igk = models.TextField(null=True)  # ИГК заявки
    znp_payment_type = models.CharField(null=True)  # Тип платежа
    znp_status = models.CharField(max_length=100, null=True)  # Статус заявки
    znp_date = models.DateField(null=True)  # Дата заявки

    class Meta:
        managed = True
        db_table = "znp_data"
        verbose_name = "Заявка на платёж"
        verbose_name_plural = "Заявки на платёж"
        # Индекс для быстрого поиска по хешу при привязке
        indexes = [models.Index(fields=["crc32_hash"])]

    def __str__(self):
        return f"{self.plan_doc}"


class ZnpDataSAP(models.Model):
    """
    Заявка на платёж SAP — рабочая таблица для заявок из SAP.

    Отдельная таблица, потому что структура заявок SAP отличается от ФЗД.
    Статус заявки определяется по датам этапов через services/sap_status.py.
    """

    id = models.AutoField(primary_key=True)

    # Поля из файла заявок SAP
    igk = models.CharField(null=True)  # ИГК
    cfo = models.CharField(null=True, max_length=4)  # ЦФО (4 символа)
    c_agent = models.CharField()  # Контрагент
    reg_num = models.CharField(null=True)  # Регистрационный номер
    items = models.CharField(null=True)  # Предметы
    vv_sum = models.FloatField(null=True)  # Сумма ВВ
    bank_name = models.CharField(null=True)  # Банк

    # Даты этапов заявки (используются для определения статуса)
    stage_e = models.DateField(null=True)  # Этап E
    stage_f = models.DateField(null=True)  # Этап F
    payment_possible = models.DateField(null=True)  # Возможная дата платежа
    init_payment_date = models.DateField(null=True)  # Изначальная дата платежа
    normalize_doc_num = models.CharField(null=True)  # Нормализованный номер документа

    class Meta:
        managed = True
        db_table = "znp_data_sap"
        verbose_name = "Заявка на платёж(САП)"
        verbose_name_plural = "Заявки на платёж(САП)"
        # Индексы для фильтрации на страницах
        indexes = [
            models.Index(fields=["cfo"]),  # фильтры по ЦФО
            models.Index(fields=["igk"]),  # фильтры по ИГК
        ]

    def __str__(self):
        return f"{self.reg_num}"


class StagingZnpSAPExcel(models.Model):
    """
    Staging таблица для импорта заявок SAP.

    Аналогична StagingZnpExcel, но для заявок из SAP.
    После нормализации данные переносятся в znp_data_sap.
    """

    id = models.AutoField(primary_key=True)

    # Поля соответствуют колонкам файла заявок SAP
    igk = models.CharField(null=True)  # ИГК
    cfo = models.CharField(max_length=4)  # ЦФО
    c_agent = models.CharField()  # Контрагент
    reg_num = models.CharField(null=True)  # Регистрационный номер
    items = models.CharField(null=True)  # Предметы
    vv_sum = models.FloatField(null=True)  # Сумма ВВ
    bank_name = models.CharField(null=True)  # Банк
    c_type = models.CharField()  # Тип
    stage_e = models.DateField(null=True)  # Этап E
    stage_f = models.DateField(null=True)  # Этап F
    payment_possible = models.DateField(null=True)  # Возможная дата платежа
    init_payment_date = models.DateField(null=True)  # Изначальная дата платежа
    normalize_doc_num = models.CharField(null=True)  # Нормализованный номер

    class Meta:
        managed = True
        db_table = "staging_znp_sap_excel"
        verbose_name = "Строка импорта ЗнП(САП)"
        verbose_name_plural = "Строка импорта ЗнП(САП)"

    def __str__(self):
        return f"{self.reg_num}"


# ============================================================================
# История изменений и снимки
# ============================================================================


class ContractsHistory(models.Model):
    """
    История изменений договоров.

    Записывается при каждой загрузке: если для позиции договора изменился
    статус, план, факт или сумма договора, создаётся запись с old/new значениями.

    Поле hash — бинарный хеш позиции договора (через pgcrypto.digest).
    Используется для поиска «той же» позиции в разных загрузках.
    """

    id = models.AutoField(primary_key=True)

    # Бинарный хеш позиции договора (digest от полей)
    hash = models.BinaryField()

    # Изменения статуса
    old_status = models.CharField(max_length=500, null=True)
    new_status = models.CharField(max_length=500, null=True)

    # Дата изменения в исходном файле и дата загрузки
    update_date = models.DateField(null=True)  # когда изменилось в файле
    upload_date = models.DateField(null=True)  # когда загрузили в систему

    # Изменения плана
    old_plan = models.FloatField(null=True)
    new_plan = models.FloatField(null=True)

    # Изменения факта
    old_fact = models.FloatField(null=True)
    new_fact = models.FloatField(null=True)

    # Даты, когда изменились план и факт
    plan_changed_date = models.DateField(null=True)
    fact_changed_date = models.DateField(null=True)

    # Изменения суммы договора
    old_contract_sum = models.FloatField(null=True)
    new_contract_sum = models.FloatField(null=True)

    class Meta:
        managed = True
        db_table = "contracts_history"
        verbose_name = "Изменение договора"
        verbose_name_plural = "Изменения договоров"
        # Индекс для быстрого поиска истории по позиции
        indexes = [models.Index(fields=["hash"])]

    def __str__(self):
        return f"Изменение #{self.id}"


class ContractCountsSnapshot(models.Model):
    """
    Снимок количества заключённых договоров на дату загрузки.

    Сохраняется при каждой загрузке договоров: сколько договоров заключено
    по каждой комбинации (ИГК, ЦФО, год). Используется для графиков
    «динамика заключения договоров» на dashboard.
    """

    id = models.AutoField(primary_key=True)

    # Дата загрузки (когда сделан снимок)
    upload_date = models.DateField()
    # Код ИГК
    igk = models.CharField(max_length=10)
    # ЦФО
    cfo = models.CharField(max_length=500)
    # Год (y25, y26, y27)
    year_col = models.CharField(max_length=5)
    # Количество заключённых договоров
    concluded_count = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = "contract_counts_snapshot"
        verbose_name = "Снимок количества договоров"
        verbose_name_plural = "Снимки количества договоров"
        # Уникальность: на одну дату один снимок для комбинации (ИГК, ЦФО, год)
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

    При каждой загрузке система сравнивает текущий файл с предыдущим.
    Если договор появился впервые или изменил статус с «не заключён» на «заключён»,
    создаётся запись в этом журнале.

    Используется для страницы «Журнал появившихся договоров» и выгрузок
    «Новые заключённые» и «Новые незаключённые».
    """

    id = models.AutoField(primary_key=True)

    # Дата загрузки, когда договор появился
    upload_date = models.DateField()
    # Тип появления: «новый» или «изменил статус»
    kind = models.CharField(max_length=20)
    # Причина появления: «новая запись» или «status changed»
    reason = models.CharField(max_length=20)

    # Поля договора (копия из igk_stat_data на момент появления)
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
        # Индекс для фильтрации по дате и типу появления
        indexes = [models.Index(fields=["upload_date", "kind"])]

    def __str__(self):
        return f"{self.contract} - {self.kind} на {self.upload_date}"


# ============================================================================
# Права доступа
# ============================================================================


class Access(models.Model):
    """
    Модель для определения прав доступа к разделам.

    Таблицы в базе НЕТ (managed = False). Django использует эту модель
    только для создания записей в django_content_type и django_permission.

    Права выдаются галочками на странице пользователя в админке.
    Проверка прав выполняется в middleware.py (SectionAccessMiddleware).
    """

    class Meta:
        managed = False  # Таблица не создаётся в БД
        default_permissions = ()  # Отключаем стандартные права (add/change/delete)
        # Кастомные права для разделов приложения
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
# Системные события
# ============================================================================


class SystemEvent(models.Model):
    """
    Системные события — для отслеживания времени последней загрузки.

    Используется для определения «когда данные последний раз обновлялись».
    Ключ события (event_key) уникален, например: «last_contracts_upload».
    """

    id = models.AutoField(primary_key=True)

    # Ключ события (например: «last_contracts_upload», «last_znp_upload»)
    event_key = models.CharField(max_length=50, unique=True)
    # Время события
    event_time = models.DateTimeField()

    class Meta:
        managed = True
        db_table = "system_events"
        verbose_name = "Системные события"
        verbose_name_plural = "Системные события"

    def __str__(self):
        return f"{self.event_key}-{self.event_time}"
