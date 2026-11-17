"""Сборщик решений: имена файлов, журнал и проход по учебной копии портала (без настоящего сайта)."""
from argparse import Namespace
from pathlib import Path

import pytest

from sud_parser.collect import Manifest, Row, case_number_of, file_name, safe_name

FAKE = Path(__file__).with_name("fake_portal.html")


def test_file_names_have_no_personal_names():
    assert safe_name("7517-24-00-2/45552") == "7517-24-00-2_45552"
    assert case_number_of("7517-24-00-2/45552\nГражданские дела") == "7517-24-00-2/45552"
    assert file_name("7517-24-00-2/45552", 2, "Иванова - ОСИ Звезда - решение.DOCX") == "7517-24-00-2_45552_2.docx"


def test_list_row_has_no_parties():
    from sud_parser.collect import list_row
    cells = ["7142-25-00-2/1\n12.03.2025\nГражданские дела", "Иванов И.И. против ОСИ «Дом»",
             "Межрайонный суд", "Удовлетворено", "СПОРЫ, ВОЗНИКАЮЩИЕ\nИЗ ЖИЛИЩНЫХ"]
    assert list_row(cells, 3) == {"case_number": "7142-25-00-2/1", "date": "12.03.2025", "court": "Межрайонный суд",
                                  "result": "Удовлетворено", "category": "СПОРЫ, ВОЗНИКАЮЩИЕ ИЗ ЖИЛИЩНЫХ", "page": 3}


def test_manifest_resumes(tmp_path):
    m = Manifest(tmp_path)
    m.add(Row("1/1", "удовлетворено", "Жилищные"), 1, "ok", ["1_1_1.docx"])
    m.add(Row("1/2", "отказано", "Жилищные"), 1, "нет решений", [])
    m.add(Row("1/3", "отказано", "Жилищные"), 1, "не открылось", [])
    again = Manifest(tmp_path)
    assert again.done == {"1/1", "1/2"}   # «не открылось» попробуем ещё раз
    assert again.saved == 1


def test_walk_fake_portal(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    from sud_parser.collect import Portal, walk_results

    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception as exc:  # нет Chrome на машине
            pytest.skip(f"Chrome не запускается: {exc}")
        page = browser.new_context(accept_downloads=True).new_page()
        page.goto(FAKE.as_uri())
        log: list[str] = []
        portal = Portal(page, pause=0.1, log=log.append, page_wait=2)
        args = Namespace(limit=10, max_pages=5, pause=0.1)
        walk_results(portal, Manifest(tmp_path), tmp_path, args)
        browser.close()

    files = sorted(p.name for p in tmp_path.glob("*.docx"))
    # дело 2 без решения, у дела 1 определение не скачивается; страница 2 со второго нажатия
    assert files == ["1111-25-00-2_1_1.docx", "1111-25-00-2_3_1.docx"]
    assert "Петров" in (tmp_path / "1111-25-00-2_3_1.docx").read_text(encoding="utf-8")
    statuses = {r.split(",")[0]: r.split(",")[4] for r in
                (tmp_path / "_manifest.csv").read_text(encoding="utf-8-sig").splitlines()[1:]}
    assert statuses == {"1111-25-00-2/1": "ok", "1111-25-00-2/2": "нет решений", "1111-25-00-2/3": "ok"}


def test_analyzer_skips_collector_files(tmp_path):
    from sud_parser.practice.reader import list_files
    for name in ("_manifest.csv", "_query.json", "~$temp.docx", "1_1.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert [p.name for p in list_files(tmp_path)] == ["1_1.txt"]
