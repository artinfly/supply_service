"""Вымышленные выгрузки для разработки: договоры, заявки ФЗД и заявки SAP.

Генератор пишет файлы Excel в том же виде, что приходят из учётных систем, и
загружает их обычными командами load_contracts / load_znp / load_znp_sap — так
демо-данные заодно проверяют настоящий импорт. Договоры загружаются дважды
(вторая выгрузка с изменениями), чтобы заполнились история и журнал появившихся.

Все названия вымышленные (контрагенты — буквы греческого алфавита).
"""

import random
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.core.management import call_command
from openpyxl import Workbook

from core.services.importing.excel_import import (
    CONTRACT_COLUMNS,
    ZNP_COLUMNS,
    ZNP_SAP_COLUMNS,
)
from core.services.queries import (
    ADVANCE,
    CONCLUDED,
    NOT_CONCL,
    POSTPAYMENT,
    SAP_CFO,
    TERMINATED,
    ZNP_APPROVED,
)

# Годы демо-договоров: прошлый, текущий и следующий (список годов на страницах
# потом берётся из этих данных сам — см. queries.available_years)
_THIS_YEAR = date.today().year
DEMO_YEARS = [_THIS_YEAR - 1, _THIS_YEAR, _THIS_YEAR + 1]

AGENTS = [
    "ООО «Альфа-Снаб»",
    "АО «Бета Механика»",
    "ООО «Гамма Комплект»",
    "ООО «Дельта Металл»",
    "АО «Эпсилон Электро»",
    "ООО «Дзета Пласт»",
    "ООО «Эта Резина»",
    "АО «Тета Приборы»",
    "ООО «Йота Инструмент»",
    "ООО «Каппа Кабель»",
]
ITEMS = [
    "Подшипники",
    "Электродвигатели",
    "Резинотехнические изделия",
    "Крепёжные изделия",
    "Кабельная продукция",
    "Лакокрасочные материалы",
    "Прокат чёрных металлов",
    "Гидравлические узлы",
    "Фильтрующие элементы",
    "Режущий инструмент",
]
BANKS = ["АО «Демо-банк»", "ПАО «Пример-банк»", "АО «Учебный банк»"]

# Статусы договоров: в основном заключённые, немного черновиков и расторгнутых
STATUSES = [*CONCLUDED] * 6 + [*NOT_CONCL] * 4 + [*TERMINATED]


def _day(value):
    return value.strftime("%d.%m.%Y")


def _write(path, rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    book.save(path)


class DemoData:
    """Вымышленные строки выгрузок; seed — одинаковый результат при каждом запуске."""

    def __init__(self, contracts=150, seed=1):
        self.random = random.Random(seed)
        self.today = date.today()
        self.positions = self._positions(contracts)

    def _amount(self, low, high):
        return self.random.randrange(low, high, 1000)

    def _positions(self, count):
        """Позиции договоров: ИГК → договоры → этапы графика оплаты."""
        rnd = self.random
        positions = []
        number = 0
        while number < count:
            year = rnd.choice(DEMO_YEARS)
            igk = f"{year % 100:02d}{rnd.randrange(10**22):022d}{rnd.randrange(10):d}"
            cfo = rnd.choice(SAP_CFO)
            for _ in range(rnd.randint(1, 3)):
                number += 1
                agent = rnd.choice(AGENTS)
                contract = f"Д-{number}/{year % 100:02d}"
                status = rnd.choice(STATUSES)
                item = rnd.choice(ITEMS)
                order = "" if rnd.random() < 0.1 else f"З-{rnd.randint(100, 999)}"
                stages = []
                for stage_no in range(1, rnd.randint(2, 4) + 1):
                    payment = ADVANCE if stage_no == 1 else POSTPAYMENT
                    plan = self._amount(50_000, 3_000_000)
                    paid_share = rnd.choice((0, 0, 0.3, 0.5, 1))
                    fact = round(plan * paid_share, 2) if status in CONCLUDED else 0
                    plan_day = date(year, 1, 1) + timedelta(days=rnd.randint(0, 364))
                    stages.append(
                        {
                            "igk": igk,
                            "agent": agent,
                            "cfo": cfo,
                            "contract": contract,
                            "status": status,
                            "payment": payment,
                            "item": item,
                            "order": order,
                            "plan": plan,
                            "fact": fact,
                            "stage": f"Этап {stage_no}",
                            "plan_date": _day(plan_day),
                            "year": str(year),
                        }
                    )
                total = sum(s["plan"] for s in stages)
                for stage in stages:
                    stage["contract_sum"] = total
                positions.extend(stages)
        return positions

    def contract_rows(self, positions):
        rows = [["Выгрузка договоров (демо-данные)"], list(CONTRACT_COLUMNS)]
        rows.extend(
            [p["igk"], p["agent"], p["cfo"], p["contract"], p["status"],
             p["payment"], p["item"], p["order"], p["plan"], p["fact"],
             p["plan"] - p["fact"], 0, p["stage"], p["plan_date"],
             p["contract_sum"], p["year"]]
            for p in positions
        )  # fmt: skip
        return rows

    def changed_positions(self):
        """Вторая выгрузка: часть договоров подписана, оплачена, расторгнута; есть новые."""
        rnd = self.random
        changed = []
        for original in self.positions:
            p = dict(original)
            roll = rnd.random()
            if p["status"] in NOT_CONCL and roll < 0.5:
                p["status"] = "Подписан"
            elif p["status"] in CONCLUDED and roll < 0.15:
                p["fact"] = p["plan"]
            elif roll > 0.97:
                p["status"] = TERMINATED[0]
            changed.append(p)
        return changed + self._positions(10)

    def znp_rows(self, positions):
        """Заявки ФЗД на часть этапов заключённых договоров."""
        rnd = self.random
        rows = [list(ZNP_COLUMNS)]
        for number, p in enumerate(positions, 1):
            if p["status"] not in CONCLUDED or rnd.random() < 0.4:
                continue
            plan_sum = round(p["plan"] * rnd.choice((0.3, 0.5, 1)), 2)
            approved = rnd.random() < 0.7
            paid = approved and rnd.random() < 0.5
            created = self.today - timedelta(days=rnd.randint(1, 120))
            rows.append(
                [p["igk"], p["igk"], p["agent"], f"ПД-{number:05d}", p["stage"],
                 f"Оплата: {p['item'].lower()}", p["contract"],
                 _day(created + timedelta(days=30)),
                 _day(created + timedelta(days=20)) if paid else "",
                 plan_sum, plan_sum if paid else None, p["payment"],
                 ZNP_APPROVED if approved else "На согласовании", _day(created)]
            )  # fmt: skip
        return rows

    def sap_rows(self, positions, count=120):
        """Заявки SAP: колонки по номерам (как в выгрузке), этапы согласования — датами."""
        rnd = self.random
        width = max(ZNP_SAP_COLUMNS.values()) + 1
        rows = [[f"Колонка {i + 1}" for i in range(width)]]
        for number in range(1, count + 1):
            p = rnd.choice(positions)
            created = self.today - timedelta(days=rnd.randint(0, 90))
            stage = rnd.randint(0, 4)  # насколько далеко прошла заявка
            values = {
                "igk": p["igk"] if rnd.random() > 0.05 else None,
                "cfo": p["cfo"],
                "c_agent": p["agent"],
                "reg_num": f"SAP-{created.year}-{number:05d}",
                "items": p["item"],
                "vv_sum": self._amount(10_000, 2_000_000),
                "bank_name": rnd.choice(BANKS),
                "stage_c": created + timedelta(days=2) if stage >= 1 else None,
                "stage_e": created + timedelta(days=5) if stage >= 2 else None,
                "stage_f": created + timedelta(days=8) if stage >= 3 else None,
                "payment_possible": created + timedelta(days=15),
                "c_type": "ГОЗ" if rnd.random() > 0.1 else "Прочее",
                "normalize_doc_num": f"ПП-{number:05d}" if stage == 4 else None,
                "created_date": created,
            }
            row = [None] * width
            for field, index in ZNP_SAP_COLUMNS.items():
                row[index] = values[field]
            rows.append(row)
        return rows


def seed(contracts=150, seed_value=1, stdout=None):
    """Создаёт файлы во временной папке и загружает их командами загрузки."""
    data = DemoData(contracts, seed_value)
    second = data.changed_positions()
    with tempfile.TemporaryDirectory() as folder:
        files = {
            "contracts_1.xlsx": data.contract_rows(data.positions),
            "contracts_2.xlsx": data.contract_rows(second),
            "znp.xlsx": data.znp_rows(second),
            "znp_sap.xlsx": data.sap_rows(second),
        }
        for name, rows in files.items():
            _write(Path(folder) / name, rows)
        out = {"stdout": stdout} if stdout else {}
        call_command("load_contracts", str(Path(folder) / "contracts_1.xlsx"), **out)
        call_command("load_contracts", str(Path(folder) / "contracts_2.xlsx"), **out)
        call_command("load_znp", str(Path(folder) / "znp.xlsx"), **out)
        call_command("load_znp_sap", str(Path(folder) / "znp_sap.xlsx"), **out)
