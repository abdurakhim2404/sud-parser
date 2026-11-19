"""Выгрузка в формат «Реестра судебных решений ЖКХ»."""
from sud_parser.practice.extract import parse_decision
from sud_parser.practice.registry import (
    COLUMNS, Meta, category, city_latin, party_type, place, safe_case, to_row,
)
from tests.test_practice import DEBT


def test_row_follows_registry_rules():
    d = parse_decision(DEBT, "debt.txt")
    row = dict(zip(COLUMNS, to_row(d, Meta("СПОРЫ, ВОЗНИКАЮЩИЕ ИЗ ЖИЛИЩНЫХ ПРАВООТНОШЕНИЙ О взыскании платы за жилье "
                                           "и коммунальные услуги", "2026-11-17"), {}, "Тестов Т.", "decisions/x.docx")))
    assert len(row) == 24
    assert row["Ответчик"] == "Физлицо" and row["Тип ответчика"] == "Жилец / собственник"
    assert row["Тип истца"] == "ОСИ"
    assert row["ID категории"] == "47"
    assert row["Вердикт"] == "Удовлетворено полностью"
    assert row["Взыскано, тг"].isdigit()
    assert "Петров" not in " ".join(row.values())


def test_helpers():
    assert safe_case("7142-25-00-2/18896") == "7142-25-00-2_18896"
    assert city_latin("Астана") == "astana" and city_latin("Усть-Каменогорск") == "ust-kamenogorsk"
    assert category("СПОРЫ, ВОЗНИКАЮЩИЕ ИЗ ЖИЛИЩНЫХ ПРАВООТНОШЕНИЙ")[0] == "212"
    assert category("СПОРЫ О ВОЗМЕЩЕНИИ УЩЕРБА")[0] == "20"
    assert category("ТРУДОВЫЕ СПОРЫ") == ("", "")
    assert party_type("ТОО «Астанаэнергосбыт»", True) == "Поставщик услуг"
    assert party_type("Республиканское государственное учреждение «Управление государственных доходов»", True) \
        == "Госорган / акимат"
    assert party_type("Потребительский кооператив собственников КСК «Дом»", False) == "КСК"
    assert party_type("Иванов Иван Иванович", False) == "Жилец / собственник"


def test_place_from_court_when_no_city():
    from sud_parser.practice.extract import Decision
    d = Decision(file="", court="Глубоковский районный суд Восточно-Казахстанской области")
    assert place(d) == "Восточно-Казахстанская область"
    assert place(Decision(file="", city="Өскемен")) == "Усть-Каменогорск"
