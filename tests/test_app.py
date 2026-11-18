"""Окно анализа (streamlit): открывается, разбирает папку, все вкладки строятся без ошибок."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.test_practice import DEBT, KZ_TEXT, PARTIAL_TEXT, REFUSAL, RULING  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "sud_parser" / "practice" / "app.py")


def test_app_analyzes_folder(tmp_path):
    for name, text in [("debt.txt", DEBT), ("refusal.txt", REFUSAL), ("partial.txt", PARTIAL_TEXT),
                       ("ruling.txt", RULING), ("kz.txt", KZ_TEXT)]:
        (tmp_path / name).write_text(text, encoding="utf-8")

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.radio[0].options[0] in ("Демо-данные", "Загрузить файлы")

    at.radio[0].set_value("Папка на компьютере").run()
    at.text_input[0].input(str(tmp_path)).run()
    at.button[0].click().run()
    assert not at.exception

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Файлов"] == "5"
    assert metrics["Решений в анализе"] == "4"          # определение исключено
    assert metrics["Исключено и не прочитано"] == "1"
    assert len(at.tabs) == 5

    # фильтр и подробный просмотр другого решения не ломают страницу
    at.multiselect[0].select(at.multiselect[0].options[0]).run()
    at.selectbox[0].select(at.selectbox[0].options[-1]).run()
    at.toggle[0].set_value(True).run()
    assert not at.exception


def test_app_reports_missing_folder(tmp_path):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.radio[0].set_value("Папка на компьютере").run()
    at.text_input[0].input(str(tmp_path / "нет такой")).run()
    at.button[0].click().run()
    assert any("Папка не найдена" in e.value for e in at.error)


def test_app_opens_demo_data_immediately(monkeypatch):
    from sud_parser.practice.demo import DEMO_FILE
    if not DEMO_FILE.exists():
        pytest.skip("нет demo/decisions.json")
    monkeypatch.setenv("SUD_PARSER_HOSTED", "1")
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert at.radio[0].options == ["Демо-данные", "Загрузить файлы"]  # на хостинге нет папок компьютера
    metrics = {m.label: m.value for m in at.metric}
    assert int(metrics["Решений в анализе"]) > 100
    at.selectbox[0].select(at.selectbox[0].options[5]).run()
    assert not at.exception


def test_demo_roundtrip_keeps_statistics(tmp_path):
    from sud_parser.practice.analyze import outcome_table, select_decisions, side_group
    from sud_parser.practice.demo import load, save
    from sud_parser.practice.extract import parse_decision
    from tests.test_practice import DEBT, PARTIAL_TEXT, REFUSAL
    result = select_decisions([parse_decision(DEBT, "Иванов долг.txt"), parse_decision(REFUSAL),
                               parse_decision(PARTIAL_TEXT)])
    save(result, tmp_path / "d.json", "тест")
    back, source = load(tmp_path / "d.json")
    assert source == "тест"
    before = [(r.label, r.won, r.partly, r.lost) for r in outcome_table(result.decisions, side_group)]
    after = [(r.label, r.won, r.partly, r.lost) for r in outcome_table(back.decisions, side_group)]
    assert before == after
    text = (tmp_path / "d.json").read_text(encoding="utf-8")
    assert "Петров" not in text and "Сидоров" not in text  # ФИО сторон не попали в файл (имя судьи остаётся)
