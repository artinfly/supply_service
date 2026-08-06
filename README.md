# supply_service

Техническое задание и регламент эксплуатации.

## 1. Назначение

Веб-приложение отчётности отдела снабжения. Принимает выгрузки Excel по
договорам и заявкам на платёж, хранит их в PostgreSQL, отображает сводные
показатели и реестры, формирует выгрузки Excel.

## 2. Окружение

| Компонент | Версия |
| --- | --- |
| Python | 3.13 |
| Django | 6.0.2 |
| PostgreSQL | 15 и выше |
| psycopg2-binary | 2.9.11 |
| openpyxl | 3.1.5 |
| WhiteNoise | 6.12.0 |
| Bootstrap | 5.3.3 |
| Chart.js | 4.5.0 |

Доступ в интернет не требуется. Пакеты Python устанавливаются из каталога
`wheels/`, Bootstrap и Chart.js хранятся в `reports/static/vendor/`.

Обязательное расширение PostgreSQL — `pgcrypto`. Без него не работают история
изменений и поиск дубликатов.

## 3. Состав

```text
supply_service/
├── manage.py
├── requirements.txt
├── wheels/                       пакеты для установки без интернета
│
├── supply_service/
│   ├── settings.py               общие настройки, одинаковы на всех машинах
│   ├── local_settings.py         настройки машины, в репозиторий не входит
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
└── reports/
    ├── models.py                 схема базы
    ├── admin.py
    ├── urls.py                   маршруты приложения
    ├── apps.py
    │
    ├── views/
    │   ├── pages.py              HTML-страницы
    │   ├── api.py                JSON для таблиц и графиков
    │   └── exports.py            выгрузки Excel
    │
    ├── services/
    │   ├── excel_import.py       чтение xlsx в staging_*, перечни колонок
    │   ├── normalize.py          перенос staging_* в рабочие таблицы
    │   ├── linking.py            crc32-хеш, привязка ЗнП к договорам
    │   ├── queries.py            SQL реестров и отчётов, общие константы
    │   ├── charts.py             SQL графиков
    │   ├── dashboards.py         расчёт показателей
    │   ├── sap_status.py         статус заявки SAP по датам этапов
    │   ├── excel.py              сборка книги xlsx
    │   └── pivot.py              выгрузка авансов по шаблону
    │
    ├── management/commands/
    │   ├── load_contracts.py
    │   ├── load_znp.py
    │   ├── load_znp_sap.py
    │   └── setup_groups.py
    │
    ├── migrations/               0001 … 0011
    ├── templates/                19 шаблонов
    ├── templatetags/
    └── static/
        ├── css/style.css
        ├── js/charts.js
        ├── img/
        ├── files/templateIGK.xlsx
        └── vendor/               Bootstrap, Chart.js
```

## 4. Настройки

`settings.py` входит в репозиторий и одинаков на всех машинах. Его править
запрещено — параметры, различающиеся между машинами, задаются в
`supply_service/local_settings.py`. Этот файл в репозиторий не входит, у каждой
машины он свой и создаётся один раз при развёртывании.

Состав `local_settings.py`:

```python
DEBUG = False

ALLOWED_HOSTS = ["10.10.10.37"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "имя_базы",
        "USER": "пользователь",
        "PASSWORD": "пароль",
        "HOST": "10.10.10.37",
        "PORT": "5432",
        "OPTIONS": {"client_encoding": "UTF8"},
    }
}
```

Значения в `settings.py` рассчитаны на локальную разработку: `DEBUG = False`,
база `supply_service_test` на `localhost`. Если `local_settings.py` отсутствует,
приложение запускается с этими значениями.

`local_settings.py` не входит в репозиторий, поэтому копирование каталога
проекта с флешки его затирает. Переносить изменения только через git.

## 5. Развёртывание

Создать базу и расширение:

```sql
CREATE DATABASE supply_service_test;
CREATE USER root WITH PASSWORD 'root';
GRANT ALL PRIVILEGES ON DATABASE supply_service_test TO root;
\c supply_service_test
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Установить окружение:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --no-index --find-links=wheels -r requirements.txt
```

Создать `supply_service/local_settings.py` по образцу из раздела 4.

Применить схему и запустить:

```bash
python manage.py migrate
python manage.py setup_groups
python manage.py createsuperuser
python manage.py collectstatic
python manage.py runserver
```

`collectstatic` обязателен при `DEBUG = False`: статику раздаёт WhiteNoise с
манифестом, без сборки страницы не отрисуются.

Приложение доступно по адресу `/reports/`.

## 6. Регламент переноса изменений

Единственный источник схемы базы — каталог `reports/migrations`. Расхождение
между файлами миграций и таблицей `django_migrations` в базе останавливает
`migrate`.

### Правила

1. Файлы миграций создаются только командой `makemigrations` и только на одной
   машине — той, где менялись модели. На остальные они попадают через git.
2. Готовый файл миграции не редактируют и не удаляют после того, как он
   применён хотя бы к одной базе.
3. Миграции не создают на сервере. Сервер только применяет то, что пришло.
4. Перед переносом на сервер проверяют, что схема и модели совпадают:

```bash
python manage.py makemigrations --check --dry-run
```

Ответ `No changes detected` означает, что незакоммиченных изменений схемы нет.

### Порядок обновления сервера

```bash
git pull
pip install --no-index --find-links=wheels -r requirements.txt
python manage.py migrate --plan
python manage.py migrate
python manage.py collectstatic --noinput
```

`migrate --plan` показывает список миграций к применению, ничего не меняя.
Если список неожиданный — остановиться и разобраться до `migrate`.

### Диагностика расхождений

Что применено в базе:

```sql
SELECT name, applied FROM django_migrations WHERE app = 'reports' ORDER BY id;
```

Что видит Django (`[X]` — применена, `[ ]` — нет):

```bash
python manage.py showmigrations reports
```

### Типовые расхождения

**В базе есть запись о миграции, файла нет.**

Возникает, когда миграцию применили, а потом удалили файл. `migrate` падает с
`InconsistentMigrationHistory`. Устранение: вернуть файл из git. Если он был
временным и таблиц за собой не оставил — удалить запись:

```sql
DELETE FROM django_migrations WHERE app = 'reports' AND name = 'имя_миграции';
```

**Файл есть, в базе записи нет, но таблица или колонка уже существуют.**

Возникает, когда схему меняли руками через SQL. `migrate` падает на
`DuplicateColumn` или `DuplicateTable`. Устранение: отметить миграцию
применённой без выполнения:

```bash
python manage.py migrate reports номер_миграции --fake
```

**Две ветки создали миграции с одинаковым номером.**

Возникает, когда `makemigrations` запускали на двух машинах. Django сообщает
`Conflicting migrations detected`. Устранение: удалить свою миграцию, забрать
чужую через `git pull`, выполнить `makemigrations` заново.

**Расхождение версий Django.**

Файл миграции, созданный новой версией Django, может не примениться на старой.
Версия из `requirements.txt` должна совпадать на всех машинах. Проверка:

```bash
python -c "import django; print(django.get_version())"
```

### Что делать нельзя

- Удалять и пересоздавать миграции на рабочей базе.
- Сворачивать историю миграций. При сворачивании истории git каталог
  `reports/migrations/` исключать.
- Править структуру таблиц напрямую в SQL мимо миграций.
- Копировать `settings.py` между машинами.
- Переносить каталог `migrations` файлами через флешку в обход git.
- Восстанавливать внешний ключ `znp_data → igk_stat_data`. Таблица
  `igk_stat_data` очищается при каждой загрузке, `pp_id` выдаются заново;
  связь держится на `crc32_hash` через `relink_znp_parents()`.

### Приведение разошедшейся базы к проекту

Эталон — база, собранная миграциями с нуля. Порядок:

1. Снять дамп: `pg_dump -h ХОСТ -U ПОЛЬЗОВАТЕЛЬ -d БАЗА -Fc -f backup.dump`
2. Сравнить структуру с эталонной: `pg_dump --schema-only` с обеих баз,
   затем сравнить полученные файлы
3. Устранить расхождения структуры
4. `DELETE FROM django_migrations WHERE app = 'reports';`
5. `python manage.py migrate reports --fake`
6. Проверить: `python manage.py showmigrations reports` — все строки с `[X]`

Шаг 4 удаляет только журнал, данные и таблицы не трогает. Шаг 5 записывает
журнал заново, ничего не выполняя, поэтому структура на шаге 3 должна уже
совпадать с эталоном.

### Заявки без привязки к договору

Заявка ФЗД связывается с позицией договора по `crc32_hash` от четырёх полей:
ИГК, контрагент, договор, этап графика. Если хотя бы одно поле в двух
выгрузках записано по-разному, привязки не будет и заявка не попадёт ни на
одну страницу — все выборки идут через `parent`.

Полей связки в `znp_data` нет, они остаются только в `staging_znp_excel` и
доступны до следующей загрузки ЗнП. Непривязанные заявки с их полями:

```sql
SELECT s.igk, s.c_agent, s.contract, s.stage, count(*) AS cnt
FROM znp_data z
JOIN staging_znp_excel s ON s.crc32_hash = z.crc32_hash
WHERE z.parent_id IS NULL
GROUP BY 1, 2, 3, 4 ORDER BY cnt DESC LIMIT 15;
```

В каком именно поле расхождение — по числу совпадений при сужении ключа:

```sql
SELECT
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM igk_stat_data i
    WHERE i.igk = s.igk AND i.c_agent = s.c_agent
      AND i.contract = s.contract AND TRIM(i.stage) = TRIM(s.stage))) AS все_четыре,
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM igk_stat_data i
    WHERE i.igk = s.igk AND i.c_agent = s.c_agent
      AND i.contract = s.contract)) AS без_этапа,
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM igk_stat_data i
    WHERE i.igk = s.igk AND i.contract = s.contract)) AS игк_и_договор,
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM igk_stat_data i
    WHERE i.igk = s.igk)) AS только_игк,
  count(*) AS всего
FROM staging_znp_excel s;
```

Резкий скачок между соседними столбцами указывает на поле, которое
расходится.

## 7. Схема данных

| Таблица | Назначение |
| --- | --- |
| `staging_excel` | строки файла договоров |
| `staging_znp_excel` | строки файла ЗнП (ФЗД) |
| `staging_znp_sap_excel` | строки файла ЗнП (SAP) |
| `igk_stat_data` | позиции договоров |
| `znp_data` | заявки на платёж (ФЗД) |
| `znp_data_sap` | заявки на платёж (SAP) |
| `contracts_history` | изменения статуса, плана, факта, суммы договора |
| `contract_counts_snapshot` | количество заключённых договоров на дату |
| `nsi_cfo`, `nsi_igk` | справочники ЦФО и ИГК |

Таблицы `staging_*` очищаются при каждой загрузке.

Миграции:

| Номер | Содержание |
| --- | --- |
| `0001_initial` | создание таблиц |
| `0002_performance_indexes_and_snapshot_key` | индексы, уникальный ключ снимка |
| `0003_sap_indexes` | индексы по ЦФО и ИГК в `znp_data_sap` |
| `0004_znp_status` | статус заявки в `znp_data` |
| `0005_contract_sum` | сумма договора в `igk_stat_data`, `contracts_history` |
| `0006_staging_contract_sum` | сумма договора в `staging_excel` |
| `0007_drop_staging_sozdan` | удаление неиспользуемой колонки |
| `0008_testtable`, `0009_delete_testtable` | служебные, на схему не влияют |
| `0010_igkstatdata_remainder_stagingexcel_ostatok` | колонка «Остаток» |
| `0011_alter_igkstatdata_remainder` | `remainder` приведён к числу |

## 8. Загрузка данных

Через веб — страница `/reports/upload/`, доступна суперпользователю и группе
`operator`. Из командной строки:

```bash
python manage.py load_contracts путь\к\кдр.xlsx
python manage.py load_znp путь\к\фзд.xlsx
python manage.py load_znp_sap путь\к\сап.xlsx
```

Команда читает файл в `staging_*` и разбирает его в рабочие таблицы. Оба шага
выполняются в одной транзакции: при ошибке база остаётся в прежнем состоянии.

Порядок загрузки произвольный. `load_contracts` полностью перезаписывает
`igk_stat_data` и в конце вызывает `relink_znp_parents()`: заявки ФЗД
привязываются к договорам заново по `crc32_hash`, а заявки, договор которых
отсутствует в новой выгрузке, привязку теряют.

## 9. Формат входных файлов

Строка заголовков определяется по названиям колонок, её положение в файле
значения не имеет. При отсутствии хотя бы одной колонки загрузка отменяется с
сообщением «Документ не соответствует формату». Перечни колонок заданы в
`services/excel_import.py`.

**Договоры (КДР):** ИГК, Контрагент, ЦФО, Договор, Состояние, Тип платежа,
Предмет, Заказ, ПЛАН, ФАКТ, Остаток, Тол, Этап графика, ДатаПланПодп,
СУММА договора, ГодИГК.

Колонка «Остаток» обязательна. Файл КДР без неё не загрузится.

**ЗнП (ФЗД):** ИГК договора, ИГК заявки, Контрагент, ДокументПланирования.Номер,
Этап, Назначение платежа, Договор, Прогнозная дата оплаты, Фактическая дата
оплаты, Сумма руб планирования, Сумма руб оплаты, ТипПлатежа, Статус.

**ЗнП (SAP):** ИГК (по договору), Отдел-исполнитель, Наименование кредитора,
Регистрационный номер, Текст, Сумма во ВВ, Наименование Банка,
ЗнП 421 отдел (ГОЗ) - (E), ЗнП 18 отдел (ГОЗ) - (F), Платеж возможен - ( ),
СП/ГП, ДокумВыравнивания.

## 10. Маршруты

Все адреса начинаются с `/reports/`.

### Страницы

| Адрес | Содержимое |
| --- | --- |
| `/` | главная |
| `dashboard/` | сводка по договорам |
| `znp/` | сводка ЗнП (ФЗД) |
| `znp-sap/` | сводка ЗнП (SAP) |
| `all-contracts/` | реестр договоров |
| `znp-list/` | реестр ЗнП (ФЗД) |
| `znp-sap-list/` | реестр ЗнП (SAP) |
| `kdr/<год>/` | КДР |
| `igk-concluded/<год>/` | заключённые по ИГК |
| `igk-not-concluded/<год>/` | незаключённые по ИГК |
| `igk-terminated/<год>/` | расторгнутые по ИГК |
| `history-status/`, `history-plan/`, `history-fact/` | история изменений |
| `contract-dupes/` | дубликаты договоров |
| `upload/` | загрузка файлов |
| `export/` | выгрузки |
| `login/`, `logout/` | вход и выход |

### Выгрузки Excel

`export/kdr/<год>/`, `export/advances/<год>/`, `export/contracts/<год>/`,
`export/history-status/`, `export/history-plan/`, `export/history-fact/`,
`export/contract-dupes/`.

### JSON

`api/kdr/<год>/`, `api/igk-concluded/<год>/`, `api/igk-not-concluded/<год>/`,
`api/igk-terminated/<год>/`, `api/igk-detail/<год>/<игк>/`, `api/all-contracts/`,
`api/znp/`, `api/znp-sap/`, `api/history-status/`, `api/history-plan/`,
`api/history-fact/`, `api/contract-dupes/`, `api/contract-dupes-by-order/`,
`api/chart/contracts/`, `api/chart/znp/`, `api/chart/znp-sap/`.

Год принимается только из списка `YEARS`. Страницы при недопустимом годе
подставляют последний год списка, JSON отвечает кодом 400.

## 10a. Отбор «не оформлено» по допуску

Для позиций договора, у которых нет ЗнП, считается допуск:

```text
допуск = Тол / 100 * Сумма договора
```

Пустой «Тол» и пустая «Сумма договора» считаются нулём, отрицательный допуск
приводится к нулю. Позиция попадает в «Не оформлено», только если остаток
строго больше допуска. Равный, меньший, нулевой и отрицательный остаток
позицию исключают — она не входит ни в плашки «Не оформлено», ни в счётчик
«Всего ЗнП», ни в проценты, ни в реестр, ни в график.

Позиции, у которых ЗнП есть, правилом не затрагиваются.

Условие задано один раз в `queries.needs_znp()` и используется тремя местами:
плашками и таблицей по ЦФО в `views/pages.py`, реестром в `views/api.py`,
графиком по ЦФО в `services/charts.py`.

## 11. Права доступа

| Роль | Права |
| --- | --- |
| суперпользователь | все страницы, включая сводки и загрузку |
| группа `operator` | загрузка файлов |
| прочие | страницы и выгрузки |

Группа создаётся командой `python manage.py setup_groups`.

## 12. Общие константы

Заданы в `services/queries.py` и действуют на все отчёты:

| Константа | Назначение |
| --- | --- |
| `CONCLUDED`, `NOT_CONCL`, `TERMINATED` | статусы договора |
| `ADVANCE`, `POSTPAYMENT` | типы платежа |
| `ZNP_APPROVED` | статус утверждённой заявки |
| `YEARS`, `YEAR_COL` | годы и колонки-флаги |
| `HAS_ORDER` | условие наличия заказа у строки |
| `needs_znp()` | условие «остаток превышает допуск» |
| `SAP_CFO` | отделы МТО (420–429) |

`HAS_ORDER` продублирован в ORM как `HAS_ORDER_Q` в `views/pages.py`. При
изменении править оба.

## 13. Добавление года

На примере 2028:

1. `services/queries.py` — `YEARS = [2025, 2026, 2027, 2028]`
2. `models.py` — поле `y28 = models.BooleanField(null=True)` в `IgkStatData`
3. `services/normalize.py` — `y28` в распаковку `year_flags()`, в кортеж
   `new_data.append(...)` и в перечень колонок INSERT
4. `makemigrations`, затем перенос по регламенту из раздела 6
