"""Демо-данные для локальной разработки и показа проекта.

    python manage.py generate_demo_data            # спросит подтверждение
    python manage.py generate_demo_data --yes      # без вопроса
    python manage.py generate_demo_data --contracts 1200 --seed 7

Все данные вымышленные: номера ИГК, контрагенты, договоры, суммы. Команда
ОЧИЩАЕТ рабочие таблицы проекта (договоры, ЗнП, история, справочник ГК,
staging) и заполняет их заново. Пользователи и права не трогаются.

Работает только при DEBUG=True, чтобы случайно не стереть данные на сервере.

Что получается (при значениях по умолчанию):
  * ~700 договоров по 8 ИГК и 10 ЦФО на 2025–2027 годы, 3–4 тыс. позиций;
  * заявки ФЗД, привязанные к позициям, во всех статусах сводки;
  * ~1500 заявок SAP на разных этапах, в том числе созданные сегодня и вчера;
  * история изменений статусов, плана и факта за последние месяцы;
  * еженедельные снимки числа заключённых договоров (для «Заключено за период» в КДР);
  * справочник ГК для «Анализа ГОЗ» во всех форматах ключа.
"""

import hashlib
import random
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from core.models import (
    ContractCountsSnapshot,
    ContractsAppeared,
    ContractsHistory,
    GozContractVat,
    IgkStatData,
    NsiIgk,
    SystemEvent,
    ZnpData,
    ZnpDataSAP,
)
from core.services.importing.linking import contract_hash
from core.services.queries import (
    ADVANCE,
    CONCLUDED,
    POSTPAYMENT,
    SAP_CFO,
    YEARS,
    ZNP_APPROVED,
)

# Таблицы, которые очищаются перед генерацией (порядок не важен — FK без ограничений)
TABLES = (
    "igk_stat_data",
    "znp_data",
    "znp_data_sap",
    "contracts_history",
    "contracts_appeared",
    "contract_counts_snapshot",
    "nsi_igk",
    "goz_contract_vat",
    "staging_excel",
    "staging_znp_excel",
    "staging_znp_sap_excel",
    "system_events",
)

# --- Справочные значения (вымышленные) ---

# Последние 4 цифры — код ИГК, который видит пользователь
IGK_CODES = ("0276", "1123", "3648", "5207", "6766", "8131", "9022", "9741")

AGENTS = (
    "АО «Уралметиз»",
    "ООО «Сибирские подшипники»",
    "АО «Волжский кабельный завод»",
    "ООО «ТехноПрокат»",
    "АО «Камский электромеханический завод»",
    "ООО «Гидросила-Урал»",
    "ООО «РезинТехПром»",
    "АО «Северсталь-Комплект»",
    "ООО «ЛКМ Холдинг»",
    "ООО «Фильтр-Сервис»",
    "АО «Электроагрегат»",
    "ООО «ПромКрепёж»",
    "АО «Челябинский трубный комбинат»",
    "ООО «АккумТех»",
    "ООО «Оптика-Приборы»",
    "АО «Тяжмаш-Снаб»",
    "ООО «Уральская литейная компания»",
    "ООО «СпецСталь»",
    "АО «Пермские моторы»",
    "ООО «Энергокомплект»",
    "ООО «ТрансДеталь»",
    "АО «Курганский арматурный завод»",
    "ООО «Полимер-Профиль»",
    "ООО «Стекло-Триплекс»",
    "АО «Навигационные системы»",
    "ООО «Радиодеталь»",
    "ООО «Шинный центр»",
    "АО «Нижегородский инструментальный завод»",
    "ООО «Тормозные системы»",
    "ООО «КомплектСнаб»",
    "АО «Металлоконструкция»",
    "ООО «Сварочные технологии»",
    "ООО «ГидроПривод»",
    "АО «Ижевский приборный завод»",
    "ООО «Уплотнитель»",
    "ООО «Электрощит-Урал»",
)

ITEMS = (
    "Подшипники качения",
    "Прокат листовой",
    "Кабельная продукция",
    "Резинотехнические изделия",
    "Электродвигатели",
    "Крепёжные изделия",
    "Лакокрасочные материалы",
    "Гидроцилиндры",
    "Фильтры топливные",
    "Аккумуляторные батареи",
    "Приборы наблюдения",
    "Отливки стальные",
    "Трубы бесшовные",
    "Запорная арматура",
    "Профиль полимерный",
    "Стёкла триплекс",
    "Аппаратура связи",
    "Радиоэлектронные компоненты",
    "Шины специальные",
    "Режущий инструмент",
    "Тормозные колодки",
    "Сварочные материалы",
    "Гидронасосы",
    "Уплотнения",
    "Электрощитовое оборудование",
)

BANKS = ("ПАО Сбербанк", "Банк ВТБ (ПАО)", "АО «Газпромбанк»", "ПАО «Промсвязьбанк»")

# Статусы договора и их доля среди всех договоров
STATUS_WEIGHTS = (
    ("Исполняется", 24),
    ("Подписан", 18),
    ("Исполнен", 15),
    ("На согласовании", 10),
    ("На утверждении", 6),
    ("Возвращен на уточнение", 4),
    ("Приостановлен", 3),
    ("Черновик", 14),
    ("Расторгнут", 6),
)

# Путь договора по статусам — для правдоподобной истории изменений
STATUS_FLOW = (
    "Черновик",
    "На согласовании",
    "На утверждении",
    "Подписан",
    "Исполняется",
    "Исполнен",
)

CFO_LIST = list(SAP_CFO)  # 420–429
CENT = Decimal("0.01")


def money(value):
    """Число в Decimal с копейками."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def history_hash(row):
    """MD5 позиции — так же, как в normalize_contracts и queries._HISTORY_JOIN."""
    parts = (row.igk, row.c_agent, row.contract, row.item, row.order, (row.stage or "").strip(), row.plan_date)
    return hashlib.md5("".join(p or "" for p in parts).encode()).digest()


class Command(BaseCommand):
    help = "Заполняет базу демо-данными (только при DEBUG=True; рабочие таблицы очищаются)"

    def add_arguments(self, parser):
        parser.add_argument("--contracts", type=int, default=700, help="Сколько договоров создать")
        parser.add_argument("--seed", type=int, default=2026, help="Зерно случайных чисел (одинаковое = одинаковые данные)")
        parser.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Демо-данные можно создавать только при DEBUG=True (не на сервере).")
        if not opts["yes"]:
            answer = input(
                f"Таблицы {', '.join(TABLES)} будут ОЧИЩЕНЫ и заполнены демо-данными. Продолжить? [y/N] "
            )
            if answer.strip().lower() not in ("y", "yes", "д", "да"):
                self.stdout.write("Отменено.")
                return

        self.rnd = random.Random(opts["seed"])
        self.today = timezone.localdate()
        # Длинные номера ИГК (25 цифр) — вымышленные, последние 4 цифры = код ИГК
        self.igks = [
            f"{self.rnd.randint(19, 25)}{self.rnd.randint(19, 26)}1873{self.rnd.randint(10**9, 10**10 - 1)}{self.rnd.randint(100, 999)}{code}"
            for code in IGK_CODES
        ]

        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY")
            NsiIgk.objects.bulk_create(NsiIgk(igk=i) for i in self.igks)
            positions = self._contracts(opts["contracts"])
            znp = self._znp(positions)
            sap = self._sap(opts["contracts"] * 2)
            history = self._history(positions)
            appeared = self._appeared(positions)
            snapshots = self._snapshots(positions)
            directory = self._directory()
            self._events()

        self.stdout.write(self.style.SUCCESS(
            "Готово: "
            f"позиций договоров {len(positions)}, заявок ФЗД {znp}, заявок SAP {sap}, "
            f"записей истории {history}, появившихся {appeared}, снимков {snapshots}, "
            f"записей справочника ГК {directory}."
        ))

    # --- Договоры ---

    def _contracts(self, count):
        """Договоры и их позиции (этапы × аванс/постоплата) в igk_stat_data."""
        rnd = self.rnd
        statuses, weights = zip(*STATUS_WEIGHTS)
        rows = []
        for n in range(1, count + 1):
            igk = rnd.choice(self.igks)
            year = rnd.choices(YEARS, weights=(4, 4, 2))[0]
            status = rnd.choices(statuses, weights=weights)[0]
            agent = rnd.choice(AGENTS)
            item = rnd.choice(ITEMS)
            contract = f"МТО-{str(year)[2:]}/{n:04d}"
            order = str(rnd.randint(284000, 286999))
            cfo = rnd.choice(CFO_LIST)
            total = money(rnd.lognormvariate(16.3, 0.9))  # в среднем ~15 млн, разброс от сотен тысяч
            tolerance = money(rnd.choice((0, 0, 5, 10)))
            stages = rnd.randint(1, 5)
            advance_share = rnd.choice((0.3, 0.4, 0.5))
            stage_sum = total / stages

            # Месяцы этапов идут по порядку внутри года договора
            months = sorted(rnd.sample(range(1, 13), stages))
            for s, month in enumerate(months, 1):
                plan_date = f"{year}.{month:02d}"
                due = date(year, month, 1)
                for payment_type, share in ((ADVANCE, advance_share), (POSTPAYMENT, 1 - advance_share)):
                    plan = money(stage_sum * Decimal(str(share)))
                    fact = self._fact(status, payment_type, plan, due)
                    rows.append(IgkStatData(
                        igk=igk, c_agent=agent, cfo=cfo, contract=contract, status=status,
                        payment_type=payment_type, item=item, order=order,
                        plan=plan, fact=fact, remainder=plan - fact, tolerance=tolerance,
                        contract_sum=total, stage=f"Этап {s}",
                        y25=year == 2025, y26=year == 2026, y27=year == 2027,
                        plan_date=plan_date, c_date=str(year),
                        crc32_hash=contract_hash(igk, agent, contract, f"Этап {s}"),
                    ))
        IgkStatData.objects.bulk_create(rows, batch_size=1000)
        return list(IgkStatData.objects.order_by("pp_id"))

    def _fact(self, status, payment_type, plan, due):
        """Фактическая оплата позиции: зависит от статуса договора и срока."""
        rnd = self.rnd
        # Незаключённые не оплачиваются; приостановленные — в основном тоже
        if status not in CONCLUDED or (status == "Приостановлен" and rnd.random() < 0.7):
            return money(0)
        if status == "Исполнен":
            return plan
        overdue = due <= self.today
        if payment_type == ADVANCE:
            chance = 0.85 if overdue else 0.25
        else:
            chance = 0.55 if overdue else 0.05
        if rnd.random() >= chance:
            return money(0)
        return plan if rnd.random() < 0.8 else money(plan * Decimal(str(rnd.uniform(0.3, 0.9))))

    # --- Заявки ФЗД ---

    def _znp(self, positions):
        """Заявки на платёж ФЗД по позициям заключённых договоров."""
        rnd = self.rnd
        rows = []
        doc = 0
        for p in positions:
            if p.status not in CONCLUDED:
                continue
            due = date(int(p.plan_date[:4]), int(p.plan_date[5:7]), 1)
            if p.fact:
                kind = "paid"
            else:
                kind = rnd.choices(("issued", "in_progress", "none"), weights=(35, 20, 45))[0]
            if kind == "none":
                continue
            doc += 1
            znp_date = min(self.today, due - timedelta(days=rnd.randint(5, 40)))
            paid = kind == "paid"
            rows.append(ZnpData(
                parent_id=p.pp_id,
                crc32_hash=p.crc32_hash,
                stage=p.stage,
                plan_doc=f"ДП-{p.c_date[2:]}-{doc:06d}",
                payment_purpose=f"{p.payment_type} по договору {p.contract}, {p.stage.lower()}: {p.item.lower()}",
                plan_payment_date=due + timedelta(days=rnd.randint(0, 25)),
                fact_payment_date=(min(self.today, due + timedelta(days=rnd.randint(0, 30))) if paid else None),
                plan_sum=p.plan,
                fact_sum=p.fact if paid else None,
                znp_igk=p.igk,
                znp_payment_type=p.payment_type,
                znp_status=ZNP_APPROVED if kind in ("paid", "issued") else "На согласовании",
                znp_date=znp_date,
            ))
        ZnpData.objects.bulk_create(rows, batch_size=1000)
        return len(rows)

    # --- Заявки SAP ---

    def _workday(self, d):
        """Ближайший рабочий день не позже d."""
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d

    def _sap(self, count):
        """Заявки SAP: этапы согласования, часть — созданные сегодня и в прошлый рабочий день."""
        rnd = self.rnd
        today = self.today
        prev = self._workday(today - timedelta(days=1 if today.weekday() else 3))
        rows = []
        for n in range(1, count + 1):
            # 6% заявок — за сегодня и прошлый рабочий день, чтобы карточки «за день» не пустовали
            r = rnd.random()
            if r < 0.03:
                created = today
            elif r < 0.06:
                created = prev
            else:
                created = self._workday(today - timedelta(days=int(rnd.expovariate(1 / 40)) + 1))
            age = (today - created).days
            stage = rnd.random()
            stage_c = stage_e = stage_f = paid_date = doc = None
            # чем старше заявка, тем дальше она продвинулась по этапам
            progress = min(4, int(age / 6) + (1 if stage < 0.5 else 0))
            if progress >= 1:
                stage_c = created + timedelta(days=rnd.randint(0, 3))
            if progress >= 2:
                # Небольшая часть получает дату передачи в будущем — «Готово к передаче»
                stage_e = stage_c + timedelta(days=rnd.randint(1, 6) + (10 if rnd.random() < 0.08 else 0))
            if progress >= 3 and stage_e <= today:
                stage_f = min(today, stage_e + timedelta(days=rnd.randint(1, 5)))
            if progress >= 4 and stage_f and rnd.random() < 0.85:
                paid_date = min(today, stage_f + timedelta(days=rnd.randint(1, 7)))
                doc = f"ПП-{paid_date:%y}-{n:06d}"
            rows.append(ZnpDataSAP(
                igk=rnd.choice(self.igks),
                cfo=rnd.choice(CFO_LIST),
                c_agent=rnd.choice(AGENTS),
                reg_num=f"45{rnd.randint(10**7, 10**8 - 1)}",
                items=rnd.choice(ITEMS),
                vv_sum=money(rnd.lognormvariate(14.6, 1.0)),
                bank_name=rnd.choice(BANKS),
                stage_c=stage_c,
                stage_e=stage_e,
                stage_f=stage_f,
                payment_possible=paid_date,
                normalize_doc_num=doc,
                created_date=created,
            ))
        ZnpDataSAP.objects.bulk_create(rows, batch_size=1000)
        return len(rows)

    # --- История изменений, появившиеся договоры, снимки ---

    def _past_date(self, max_days=120):
        return self._workday(self.today - timedelta(days=self.rnd.randint(1, max_days)))

    def _history(self, positions):
        """Изменения статуса, плана и факта между «загрузками» за последние месяцы."""
        rnd = self.rnd
        rows = []
        for p in rnd.sample(positions, k=min(len(positions), len(positions) // 6)):
            kind = rnd.choices(("status", "plan", "fact"), weights=(3, 3, 4))[0]
            d = self._past_date()
            h = ContractsHistory(hash=history_hash(p), old_contract_sum=p.contract_sum, new_contract_sum=p.contract_sum)
            if kind == "status" and p.status in STATUS_FLOW[1:]:
                h.old_status = STATUS_FLOW[STATUS_FLOW.index(p.status) - 1]
                h.new_status = p.status
                h.update_date = h.upload_date = d
            elif kind == "plan" or p.fact == 0:
                h.old_plan = money(p.plan * Decimal(str(rnd.uniform(0.8, 1.2))))
                h.new_plan = p.plan
                h.plan_changed_date = d
                old_sum = p.contract_sum + (h.old_plan - h.new_plan)
                h.old_contract_sum = old_sum
            else:
                h.old_fact = money(0) if rnd.random() < 0.7 else money(p.fact * Decimal("0.5"))
                h.new_fact = p.fact
                h.fact_changed_date = d
            rows.append(h)
        ContractsHistory.objects.bulk_create(rows, batch_size=1000)
        return len(rows)

    def _appeared(self, positions):
        """Новые позиции и смены статуса на заключённый / незаключённый."""
        rnd = self.rnd
        rows = []
        for p in rnd.sample(positions, k=min(len(positions), 150)):
            if p.status in CONCLUDED:
                kind = "concluded"
            elif p.status == "Черновик":
                kind = "not_concluded"
            else:
                continue
            rows.append(ContractsAppeared(
                upload_date=self._past_date(60),
                kind=kind,
                reason=rnd.choice(("новая позиция", "смена статуса")),
                igk=p.igk, cfo=p.cfo, c_agent=p.c_agent, contract=p.contract, item=p.item,
                order_num=p.order, stage=p.stage, plan_date=p.plan_date, status=p.status,
                plan=p.plan, contract_sum=p.contract_sum,
            ))
        ContractsAppeared.objects.bulk_create(rows)
        return len(rows)

    def _snapshots(self, positions):
        """Еженедельные снимки числа заключённых договоров: к сегодняшнему дню число растёт."""
        rnd = self.rnd
        current = {}
        for p in positions:
            if p.status in CONCLUDED:
                key = (p.igk[-4:], p.cfo, f"y{p.c_date[2:]}")
                current.setdefault(key, set()).add(p.contract)
        rows = []
        for weeks_ago in range(0, 13):
            day = self._workday(self.today - timedelta(weeks=weeks_ago))
            for (igk, cfo, year_col), contracts in current.items():
                count = max(0, len(contracts) - sum(rnd.random() < 0.12 for _ in range(weeks_ago)))
                rows.append(ContractCountsSnapshot(
                    upload_date=day, igk=igk, cfo=cfo, year_col=year_col, concluded_count=count,
                ))
        ContractCountsSnapshot.objects.bulk_create(rows, batch_size=1000, ignore_conflicts=True)
        return len(rows)

    # --- Справочник ГК («Анализ ГОЗ») ---

    def _directory(self):
        """Записи справочника во всех форматах ключа: «ИГК», «ИГК спец», «ИГК/Nсб», «ИГК/Nсб спец»."""
        rnd = self.rnd
        records = {}
        for igk in self.igks:
            code = igk[-4:]
            for _ in range(rnd.randint(5, 10)):
                sb = rnd.randint(5, 520)
                d = date(rnd.randint(2019, 2026), rnd.randint(1, 12), rnd.randint(1, 28))
                variant = rnd.random()
                if variant < 0.5:
                    key, contract = f"{code}/{sb}сб", f"{igk}/{sb}сб/137 от {d:%d.%m.%Y}г."
                elif variant < 0.8:
                    spec = rnd.randint(1, 220)
                    key = f"{code}/{sb}сб {spec}"
                    contract = f"{igk}/{sb}сб/137\nот {d:%d.%m.%Y}г., спец…./{spec}"
                elif variant < 0.9:
                    spec = rnd.randint(1, 40)
                    key, contract = f"{code} {spec}", f"{igk}/{spec} от {d:%d.%m.%Y}г."
                else:
                    key, contract = code, f"{igk}/137 от {d:%d.%m.%Y}г."
                records[key] = GozContractVat(
                    igk=key,
                    enterprise=rnd.choice(AGENTS),
                    order=str(rnd.randint(284000, 286999)),
                    contract_date=contract,
                    year=str(rnd.choice(YEARS)) if rnd.random() < 0.7 else None,
                    product=rnd.choice(ITEMS) if rnd.random() < 0.6 else None,
                    vat_rate=Decimal(rnd.choice(("22.0", "22.0", "22.0", "20.0", "10.0"))),
                )
        GozContractVat.objects.bulk_create(records.values())
        return len(records)

    def _events(self):
        """Время «последних загрузок» — надписи «Актуально на …» на сводках."""
        morning = timezone.make_aware(datetime.combine(self.today, time(8, 30)))
        for key, minutes in (("contracts_load", 0), ("znp_load", 5), ("sap_load", 10)):
            SystemEvent.objects.create(event_key=key, event_time=morning + timedelta(minutes=minutes))
