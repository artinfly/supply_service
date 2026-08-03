# supply_service

Django-приложение отчётности отдела снабжения. Данные поступают выгрузками
Excel, попадают в PostgreSQL и показываются на дашбордах, в реестрах и в
выгрузках Excel.

## Стек

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

Интернет не нужен ни при установке, ни при работе: пакеты ставятся из `wheels/`,
Bootstrap и Chart.js лежат в `reports/static/vendor/`.

## Структура

```text
supply_service/
├── manage.py
├── requirements.txt
├── pyproject.toml                настройки black и isort
├── wheels/                       пакеты для установки без интернета
│
├── supply_service/
│   ├── settings.py               база, приложения, статика
│   ├── urls.py                   подключает admin и reports
│   ├── asgi.py
│   └── wsgi.py
│
└── reports/
    ├── models.py                 схема базы
    ├── admin.py
    ├── urls.py                   все маршруты приложения
    ├── apps.py
    │
    ├── views/
    │   ├── pages.py              HTML-страницы
    │   ├── api.py                JSON для таблиц и графиков
    │   └── exports.py            выгрузки в Excel
    │
    ├── services/
    │   ├── excel_import.py       чтение xlsx в staging_*, списки колонок
    │   ├── normalize.py          staging_* -> рабочие таблицы
    │   ├── linking.py            crc32-хеш и привязка ЗнП к договорам
    │   ├── queries.py            SQL реестров и отчётов, общие константы
    │   ├── charts.py             SQL для графиков
    │   ├── dashboards.py         расчёт плашек и строк по ЦФО
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
    ├── migrations/               0001 … 0007
    ├── templates/                19 шаблонов
    ├── templatetags/
    └── static/
        ├── css/style.css
        ├── js/charts.js
        ├── img/
        ├── files/templateIGK.xlsx
        └── vendor/               Bootstrap, Chart.js
```

## Установка и запуск

Создать базу PostgreSQL и расширение `pgcrypto` — оно обязательно, на нём
работают история изменений и поиск дубликатов:

```sql
CREATE DATABASE supply_service_test;
CREATE USER root WITH PASSWORD 'root';
GRANT ALL PRIVILEGES ON DATABASE supply_service_test TO root;
\c supply_service_test
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Окружение и зависимости:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --no-index --find-links=wheels -r requirements.txt
```

Миграции, группы, учётная запись, сервер:

```bash
python manage.py migrate
python manage.py setup_groups
python manage.py createsuperuser
python manage.py runserver
```

Приложение открывается на `http://127.0.0.1:8000/reports/`.

При `DEBUG = False` перед запуском нужен `python manage.py collectstatic`:
статику раздаёт WhiteNoise с манифестом, без сборки страницы упадут.

## Настройки

`supply_service/settings.py` не одинаков дома и на работе — у каждой машины свой
экземпляр. Отличаются только параметры подключения:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "supply_service_test",
        "USER": "root",
        "PASSWORD": "root",
        "HOST": "localhost",
        "PORT": "5432",
        "OPTIONS": {"client_encoding": "UTF8"},
    }
}
```

## Таблицы базы

| Таблица | Назначение |
| --- | --- |
| `staging_excel` | сырые строки файла договоров |
| `staging_znp_excel` | сырые строки файла ЗнП (ФЗД) |
| `staging_znp_sap_excel` | сырые строки файла ЗнП (SAP) |
| `igk_stat_data` | позиции договоров |
| `znp_data` | заявки на платёж (ФЗД) |
| `znp_data_sap` | заявки на платёж (SAP) |
| `contracts_history` | изменения статуса, плана, факта и суммы договора |
| `contract_counts_snapshot` | снимок количества заключённых договоров на дату |
| `nsi_cfo`, `nsi_igk` | справочники ЦФО и ИГК |

Таблицы `staging_*` очищаются при каждой загрузке (`TRUNCATE`).

## Миграции

| Номер | Что делает |
| --- | --- |
| `0001_initial` | все таблицы |
| `0002_performance_indexes_and_snapshot_key` | индексы, уникальный ключ снимка |
| `0003_sap_indexes` | индексы по ЦФО и ИГК в `znp_data_sap` |
| `0004_znp_status` | статус заявки в `znp_data` |
| `0005_contract_sum` | сумма договора в `igk_stat_data` и `contracts_history` |
| `0006_staging_contract_sum` | сумма договора в `staging_excel` |
| `0007_drop_staging_sozdan` | убрана неиспользуемая колонка |

Проверка, что схема и модели совпадают:

```bash
python manage.py makemigrations --check --dry-run
```

## Загрузка данных

Через веб — страница `/reports/upload/`, доступна суперпользователю и группе
`operator`. Из командной строки:

```bash
python manage.py load_contracts путь\к\кдр.xlsx
python manage.py load_znp путь\к\фзд.xlsx
python manage.py load_znp_sap путь\к\сап.xlsx
```

Каждая команда читает файл в `staging_*` и сразу разбирает его в рабочие
таблицы. Оба шага в одной транзакции: при ошибке база остаётся прежней.

Порядок загрузки произвольный. `load_contracts` полностью перезаписывает
`igk_stat_data`, но в конце вызывает `relink_znp_parents()`: заявки ФЗД
привязываются к договорам заново по `crc32_hash`, а заявки, чей договор пропал
из выгрузки, теряют привязку.

## Формат файлов Excel

Строка заголовков ищется по названиям колонок, её положение в файле значения не
имеет. Если хотя бы одной колонки нет, загрузка отменяется с сообщением
«Документ не соответствует формату». Списки колонок заданы в
`services/excel_import.py`.

**Договоры (КДР):** ИГК, Контрагент, ЦФО, Договор, Состояние, Тип платежа,
Предмет, Заказ, ПЛАН, ФАКТ, Тол, Этап графика, ДатаПланПодп, СУММА договора,
ГодИГК.

**ЗнП (ФЗД):** ИГК договора, ИГК заявки, Контрагент, ДокументПланирования.Номер,
Этап, Назначение платежа, Договор, Прогнозная дата оплаты, Фактическая дата
оплаты, Сумма руб планирования, Сумма руб оплаты, ТипПлатежа, Статус.

**ЗнП (SAP):** ИГК (по договору), Отдел-исполнитель, Наименование кредитора,
Регистрационный номер, Текст, Сумма во ВВ, Наименование Банка,
ЗнП 421 отдел (ГОЗ) - (E), ЗнП 18 отдел (ГОЗ) - (F), Платеж возможен - ( ),
СП/ГП, ДокумВыравнивания.

## Маршруты

Все адреса начинаются с `/reports/`.

### Страницы

| Адрес | Содержимое |
| --- | --- |
| `/` | главная |
| `dashboard/` | дашборд по договорам |
| `znp/` | дашборд ЗнП (ФЗД) |
| `znp-sap/` | дашборд ЗнП (SAP) |
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
| `export/` | страница выгрузок |
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

Год принимается только из списка `YEARS`. Страницы при чужом годе подставляют
последний год списка, JSON отвечает 400.

## Права доступа

| Кто | Что может |
| --- | --- |
| суперпользователь | всё, включая дашборды и загрузку |
| группа `operator` | загрузка файлов |
| остальные | страницы и выгрузки |

Группу создаёт `python manage.py setup_groups`.

## Общие константы

`services/queries.py` — единственное место, где заданы значения, влияющие на
все отчёты:

| Константа | Смысл |
| --- | --- |
| `CONCLUDED`, `NOT_CONCL`, `TERMINATED` | статусы договора |
| `ADVANCE`, `POSTPAYMENT` | типы платежа |
| `ZNP_APPROVED` | статус утверждённой ЗнП |
| `YEARS`, `YEAR_COL` | годы и колонки-флаги |
| `HAS_ORDER` | условие «у строки есть заказ» |
| `SAP_CFO` | отделы МТО (420–429) |

`HAS_ORDER` продублирован в ORM как `HAS_ORDER_Q` в `views/pages.py` — при
изменении править оба.

## Добавление нового года

Например, 2028:

1. `services/queries.py` — `YEARS = [2025, 2026, 2027, 2028]`
2. `models.py` — поле `y28 = models.BooleanField(null=True)` в `IgkStatData`
3. `services/normalize.py` — `y28` в распаковку `year_flags()`, в кортеж
   `new_data.append(...)` и в список колонок INSERT
4. `makemigrations` и `migrate`

## Разработка

```bash
python -m black .
python -m isort .
python manage.py check
python manage.py makemigrations --check --dry-run
```

Профиль isort задан в `pyproject.toml` и согласован с black.
