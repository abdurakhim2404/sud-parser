from pathlib import Path

from sud_parser.input_reader import is_valid_iin, normalize_name, read_debtors
from sud_parser.models import CourtCase, Debtor, mask_iin
from sud_parser.pipeline import run
from sud_parser.sources.base import Source
from sud_parser.sources.mock import MockSource
from sud_parser.storage import CHANGED, NEW, SAME, Storage

EXAMPLE = Path(__file__).parent.parent / "input" / "debtors_example.csv"


def test_iin_checksum():
    assert is_valid_iin("900101300126")
    assert not is_valid_iin("900101300123")   # неверная контрольная цифра
    assert not is_valid_iin("12345")          # не 12 цифр
    assert not is_valid_iin("90010130012a")


def test_mask_and_normalize():
    assert mask_iin("900101300126") == "9001******26"
    assert normalize_name("  иванов   пётр ") == "ИВАНОВ ПЕТР"


def test_read_example_file():
    res = read_debtors(EXAMPLE)
    assert len(res.debtors) == 6                   # 5 с ИИН + 1 только с ФИО
    assert len(res.errors) == 2                    # неверный ИИН + дубль
    assert res.debtors[0].debt_kzt == 150000
    assert res.debtors[5].iin is None


def test_storage_detects_new_changed_same():
    st = Storage(":memory:")
    d = Debtor(iin="900101300126")
    case = CourtCase(source="t", case_number="1", status="Принято")
    assert st.save_case(case, d) == (NEW, None)
    assert st.save_case(case, d) == (SAME, "Принято")
    case.status = "Решение вынесено"
    assert st.save_case(case, d) == (CHANGED, "Принято")
    assert len(st.all_cases()) == 1                # без дублей


class BrokenSource(Source):
    name = "broken"

    def search(self, debtor):
        if debtor.iin == "850505400454":
            raise RuntimeError("сайт не ответил")
        return []


def test_one_error_does_not_stop_run():
    debtors = read_debtors(EXAMPLE).debtors
    result = run(debtors, BrokenSource(), Storage(":memory:"))
    assert len(result.errors) == 1
    assert result.not_found == len(debtors) - 1


def test_monitoring_second_run_reports_only_changes():
    debtors = read_debtors(EXAMPLE).debtors
    st = Storage(":memory:")
    first = run(debtors, MockSource(day=0), st)
    assert first.new_cases == first.cases_found > 0

    same = run(debtors, MockSource(day=0), st)
    assert same.changes == []                      # ничего не изменилось — пустой отчёт изменений

    later = run(debtors, MockSource(day=1), st)
    assert later.new_cases == 0
    assert later.changed > 0                       # часть дел продвинулась по стадиям


# ---------- portal-sot.kz: проверяем на поддельных ответах, без обращения к сайту ----------

from datetime import date

from sud_parser.sources.portal_sot_kz import PortalSotSource


class FakeResponse:
    def __init__(self, data, status=0):
        self._body = {"status": status, "data": data, "message": "сбой" if status else None}

    def json(self):
        return self._body


class FakePortalClient:
    """Отвечает как portal-sot.kz: справочник судов и график по датам."""

    def __init__(self, schedule_by_date, fail=False):
        self.schedule_by_date = schedule_by_date
        self.fail = fail
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if "dictionary/court" in url:
            return FakeResponse([{"CODE": "197142", "VALUE_RU": "Тестовый суд"}])
        if self.fail:
            return FakeResponse(None, status=4)
        return FakeResponse(self.schedule_by_date.get(url.rsplit("/", 1)[1], []))

    def close(self):
        pass


def hearing(number, defendant, time="10:00"):
    return {"uid": "1", "time": time, "judge": "СУДЬЯ Т. Т.", "hallNumber": "12", "caseNumber": number,
            "applicants": [{"name": "ОСИ \"Тестовый дом\""}], "defendants": [{"name": defendant}], "sides": None}


def portal(schedule, **kw):
    return PortalSotSource(courts=["197142"], days_back=2, days_ahead=2,
                           today=date(2026, 11, 11), client=FakePortalClient(schedule, **kw))  # среда


def test_portal_finds_defendant_by_name():
    src = portal({"2026-11-10": [hearing("7142-26-00-2/111", "Иванов  Иван Иванович")]})
    cases = src.search(Debtor(full_name="ИВАНОВ ИВАН ИВАНОВИЧ"))
    assert [c.case_number for c in cases] == ["7142-26-00-2/111"]
    c = cases[0]
    assert c.court == "Тестовый суд" and c.matched_by == "name" and c.case_date == "2026-11-10"
    assert c.status == "Заседание 10.11.2026 10:00, зал 12, судья СУДЬЯ Т. Т."
    assert src.search(Debtor(full_name="ПЕТРОВ ПЕТР ПЕТРОВИЧ")) == []


def test_portal_keeps_latest_hearing_and_loads_once():
    src = portal({"2026-11-09": [hearing("7142-26-00-2/111", "ИВАНОВ ИВАН ИВАНОВИЧ")],
                  "2026-11-12": [hearing("7142-26-00-2/111", "ИВАНОВ ИВАН ИВАНОВИЧ", time="15:30")]})
    cases = src.search(Debtor(full_name="ИВАНОВ ИВАН ИВАНОВИЧ"))
    assert len(cases) == 1 and cases[0].case_date == "2026-11-12"
    src.search(Debtor(full_name="ИВАНОВ ИВАН ИВАНОВИЧ"))
    assert len(src.client.urls) == 1 + 5          # справочник + 5 рабочих дней (9–13 ноября), без повторов


def test_portal_skips_weekends():
    src = PortalSotSource(courts=["197142"], days_back=0, days_ahead=6,
                          today=date(2026, 11, 13), client=FakePortalClient({}))  # пятница
    assert [d.isoformat() for d in src._dates()] == ["2026-11-13", "2026-11-16", "2026-11-17",
                                                     "2026-11-18", "2026-11-19"]


def test_portal_errors_are_reported_not_hidden():
    result = run([Debtor(iin="900101300126")], portal({}), Storage(":memory:"))
    assert len(result.errors) == 1                # без ФИО искать нельзя — это ошибка, а не «дел нет»

    result = run([Debtor(full_name="ИВАНОВ ИВАН ИВАНОВИЧ")], portal({}, fail=True), Storage(":memory:"))
    assert len(result.errors) == 1                # сбой портала — тоже ошибка


def test_portal_flags_incomplete_schedules():
    full_day = [hearing(f"7142-26-00-2/{n}", f"ОТВЕТЧИК НОМЕР {n}") for n in range(50)]
    src = portal({"2026-11-10": full_day, "2026-11-11": full_day[:49]})
    src.search(Debtor(full_name="ИВАНОВ ИВАН ИВАНОВИЧ"))
    assert (src.requests, src.capped_requests) == (5, 1)   # упёрся в лимит только день с 50 делами
