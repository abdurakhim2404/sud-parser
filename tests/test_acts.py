"""Выдача судебных актов в JSON и обезличивание полного текста. Все имена выдуманы."""
import json

import pytest

from sud_parser.practice import acts
from sud_parser.practice.extract import mask_document, parse_decision
from sud_parser.practice.registry import COLUMNS, Meta, party_types, to_row
from tests.test_practice import DEBT

PARTIES = ["Тестова Анна Борисовна"]


@pytest.mark.parametrize("raw, hidden, kept", [
    ("Ответчик Тестова пояснила суду", "Тестова", "Ответчик Т."),
    ("иск к Тестовой Анне Борисовне", "Тестовой", "Т. А. Б."),
    ("свидетель Ромашкина Гульнара показала", "Ромашкина", "свидетель Р. Г."),
    ("Свидетель Кумысова Айгерим в суде", "Кумысова", "С"),
    ("ЧСИ Пролеткин возбудил производство", "Пролеткин", "ЧСИ П."),
    ("Талап қоюшылар Д.Ж.Бөрібаев, представитель", "Бөрібаев", "Д.Ж.Б."),
    ("при секретаре судебного заседания Лапшиной Б. А.", "Лапшиной", "Л."),
    ("ИИН 900101300123, тел. +7 701 123 45 67", "900101300123", "[ИИН]"),
    ("г. Алматы, ул. Абая, д. 5, кв.17относится", "кв.17", "кв.[№]"),
    ("мекенжайы: 45-пәтер", "45-пәтер", "[№] пәтер"),
    ("родился 01.02.1980 года рождения", "01.02.1980", "[дата рождения]"),
])
def test_mask_document(raw, hidden, kept):
    out = mask_document(raw, PARTIES)
    assert hidden not in out
    assert kept in out


@pytest.mark.parametrize("raw", [
    "улица Сағадат Нұрмағамбетов, дом 31А",
    "Объединение собственников имущества «Шевченко 129»",
    "Налоговый Кодекс Республики Казахстан",
    "Поскольку Застройщиком не исполнено",
    "Алматы облысы, Жамбыл ауданы",
    "Гражданского процессуального кодекса",
])
def test_mask_document_keeps_places_and_terms(raw):
    assert mask_document(raw, PARTIES) == raw


def test_record_and_json(tmp_path):
    d = parse_decision(DEBT, "debt.txt")
    row = dict(zip(COLUMNS, to_row(d, Meta("СПОРЫ, ВОЗНИКАЮЩИЕ ИЗ ЖИЛИЩНЫХ ПРАВООТНОШЕНИЙ О взыскании платы за жилье "
                                           "и коммунальные услуги", "2026-11-17"), {}, "Тестов Т.", "decisions/x.docx")))
    rec = acts.to_record(d, row, DEBT, *party_types(d), link="https://example.org/x")
    assert rec["case_number"] == d.case_number and rec["verdict"] == "Удовлетворено полностью"
    assert rec["category_id"] == "47" and rec["language"] == "ru"
    assert rec["plaintiffs"][0]["type"] == "ОСИ" and rec["defendants"][0]["type"] == "Жилец / собственник"
    assert rec["source_url"] == "https://example.org/x"
    assert "Петров" not in json.dumps(rec, ensure_ascii=False)
    path = tmp_path / "acts.json"
    acts.write([rec], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["count"] == 1 and payload["format_version"] == acts.FORMAT_VERSION


def test_language():
    assert acts.language("Талап қоюшының талабы қанағаттандырылсын") == "kk"
    assert acts.language("Иск удовлетворить полностью") == "ru"
