"""Тесты анализатора судебной практики.

Тексты выдуманные, но повторяют оформление настоящих решений судов РК
(настоящие решения содержат персональные данные и в репозиторий не кладутся).
"""
from datetime import date

import docx
import pytest

from sud_parser.practice.analyze import (
    analyze_folder, article_table, money_stats, osi_won, outcome_table, select_decisions, side_group,
)
from sud_parser.practice.extract import (
    PARTIAL, REFUSED, SATISFIED, Citation, _expand_articles, classify_outcome, extract_amounts,
    extract_citations, mask_person, normalize_judge, parse_decision, split_parties,
)
from sud_parser.practice.reader import read_text

DEBT = """Р Е Ш Е Н И Е
ИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН
12 марта 2025 года\tдело №7520-25-00-2/1111\t\t город  Алматы
Районный суд №2 Алмалинского района города Алматы
в составе председательствующего судьи Иванова И.И.,
рассмотрев в открытом судебном заседании гражданское дело по иску:
ИСТЕЦ:
Объединение собственников имущества «Тестовый дом» (далее – истец)
ОТВЕТЧИК:
Петров Пётр Петрович
Сидорова Анна Сергеевна
ТРЕБОВАНИЯ ИСТЦА:
о взыскании суммы задолженности, неустойки
ОПИСАТЕЛЬНАЯ ЧАСТЬ:
Ответчики не оплачивают расходы на содержание общего имущества.
МОТИВИРОВОЧНАЯ ЧАСТЬ:
В силу пункта 1 статьи 189 Гражданского кодекса Республики Казахстан (далее – ГК) собственник несет бремя.
Согласно пункту 1 статьи 18 Закона Республики Казахстан «О жилищных отношениях» (далее – Закон), собственник квартиры.
В соответствии с пунктом 5 статьи 50 Закона начисляется пеня. Согласно статье 42-1 Закона взносы обязательны.
Согласно пункту 16 нормативного постановления Верховного Суда Республики Казахстан за №5 от 11 июля 2003 года «О судебном решении».
РЕЗОЛЮТИВНАЯ ЧАСТЬ:
Руководствуясь статьями 223-226, 267-4 ГПК, суд
РЕШИЛ:
Иск объединения собственников имущества «Тестовый дом» к Петрову П.П., Сидоровой А.С. – удовлетворить.
Взыскать с Петрова Петра Петровича в пользу ОСИ «Тестовый дом» сумму задолженности в размере 95 112 (девяносто пять тысяч сто двенадцать) тенге, неустойки в размере 18 001,50 (восемнадцать тысяч один) тенге 50 (пятьдесят) тиын, расходы по оплате государственной пошлины 3 762,31 (три тысячи) тенге 31 (тридцать один) тиын, по оплате услуг представителя 12 541 (двенадцать тысяч) тенге.
Взыскать с Сидоровой Анны Сергеевны в пользу ОСИ «Тестовый дом» задолженность в сумме 328594 (триста двадцать восемь тысяч) тенге, пеню 6092 тенге, расходы по оплате услуг представителя 50435,68 (пятьдесят тысяч) 68 тиын, судебные издержки по курьерской доставке в сумме 1050 тенге.
На решение суда могут быть поданы апелляционные жалоба в течение одного месяца.
Судья\t\t\t\tИванов И.И.
"""

REFUSAL = """РЕШЕНИЕ
ИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН
Специализированный межрайонный экономический суд города Астаны в составе:
председательствующего судьи Ахметова А.А.,
рассмотрел в открытом судебном заседании гражданское дело по иску:
ИСТЕЦ:
Объединение собственников имущества «ЖК Тест, ул. Абая, дом 1/2»
ОТВЕТЧИКИ:
Товарищество с ограниченной ответственностью «Строй Тест»
Некоммерческое акционерное общество «Государственная корпорация
«Правительство для граждан», в лице филиала по городу Астане
ТРЕТЬИ ЛИЦА, НЕ ЗАЯВЛЯЮЩИЕ САМОСТОЯТЕЛЬНЫХ ТРЕБОВАНИЙ:
ГУ «Управление тестов»
ТРЕБОВАНИЕ ИСТЦА:
Об обязании возвести паркинг
МОТИВИРОВОЧНАЯ ЧАСТЬ:
Согласно статье 654 ГК подрядчик обязан. Статьи 541, 543 ГК не применимы.
РЕШИЛ:
В удовлетворении иска объединения собственников имущества «ЖК Тест, ул. Абая, дом 1/2» к ТОО «Строй Тест» об обязании возвести паркинг на 240 000 тенге – отказать.
На решение может быть подана апелляционная жалоба.
Судья\t\t\tА.А. Ахметов
14 октября 2025 года | дело №7119-25-00-2/2222 | город Астана
"""

PARTIAL_TEXT = """РЕШЕНИЕ
ИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН
9 января 2025 года\t№ 7517-24-00-2/3333\tгород Алматы
Судья межрайонного суда по гражданским делам города Астаны Давлетова М.М., рассмотрев в порядке упрощенного (письменного) производства дело по иску:
ИСТЕЦ:
объединение собственников имущества (далее – ОСИ) «Джамбула 1»
ОТВЕТЧИК:
Касымов Ерлан
ТРЕБОВАНИЯ ИСТЦА:
о взыскании задолженности
РЕШИЛ:
Иск объединения собственников имущества «Джамбула 1», – удовлетворить.
Взыскать с Касымова Ерлана задолженность в сумме 3 740 430,81 (три миллиона) тенге, расходы по оплате исполнительной надписи в размере 4 442 тенге.
В удовлетворении остальной части иска – отказать.
Судья\tДавлетова М.М.
"""

RULING = """№7520-25-00-2/1111
О П Р Е Д Е Л Е Н И Е
29 мая 2025 года\t\tгород Алматы
Судья Районного суда №2 Алмалинского района города Алматы Иванов И.И., рассмотрев заявление ответчика
УСТАНОВИЛ:
Ответчик просит восстановить срок.
ОПРЕДЕЛИЛ:
В удовлетворении заявления о восстановлении срока – отказать.
"""


# --- разбор одного решения --------------------------------------------------------------------

def test_header_parties_and_claim():
    d = parse_decision(DEBT, "a.docx")
    assert d.doc_type == "решение"
    assert d.case_number == "7520-25-00-2/1111"
    assert d.date == date(2025, 3, 12)
    assert d.city == "Алматы"
    assert d.court == "Районный суд №2 Алмалинского района города Алматы"
    assert d.judge == "Иванов И.И."
    assert d.procedure == "судебное заседание"
    assert d.plaintiffs == ["Объединение собственников имущества «Тестовый дом»"]
    assert d.defendants == ["Петров Пётр Петрович", "Сидорова Анна Сергеевна"]
    assert d.claim == "о взыскании суммы задолженности, неустойки"
    assert d.topic.startswith("Взыскание задолженности")
    assert (d.osi_role, d.opponent) == ("истец", "физлица")
    assert d.warnings == []


def test_outcome_and_amounts_with_tiyn_and_words():
    d = parse_decision(DEBT)
    assert d.outcome == SATISFIED
    a = d.amounts
    assert a.principal == 95_112 + 328_594
    assert a.penalty == 18_001.50 + 6_092      # «неустойки» и «пеню»
    assert a.state_fee == 3_762.31
    assert a.lawyer == 12_541 + 50_435.68     # вторая сумма без слова «тенге», только «68 тиын»
    assert a.other_costs == 1_050


def test_citations_resolve_aliases_and_ranges():
    d = parse_decision(DEBT)
    material = {(c.law, c.article) for c in d.citations if not c.procedural}
    assert material == {
        ("ГК", "189"),
        ("Закон «О жилищных отношениях»", "18"),
        ("Закон «О жилищных отношениях»", "50"),     # «статьи 50 Закона» через «(далее – Закон)»
        ("Закон «О жилищных отношениях»", "42-1"),
    }
    procedural = {c.article for c in d.citations if c.procedural}
    assert procedural == {"223", "224", "225", "226", "267-4"}
    assert d.resolutions == ["О судебном решении"]


def test_refusal_org_defendants_multiline_names_and_footer_date():
    d = parse_decision(REFUSAL)
    assert d.outcome == REFUSED
    assert d.case_number == "7119-25-00-2/2222"
    assert d.date == date(2025, 10, 14)            # дата в таблице внизу
    assert d.plaintiffs == ["Объединение собственников имущества «ЖК Тест, ул. Абая, дом 1/2»"]
    assert len(d.defendants) == 2                  # название НАО перенесено на вторую строку
    assert d.defendants[1].startswith("Некоммерческое акционерное общество «Государственная корпорация")
    assert d.third_parties == ["ГУ «Управление тестов»"]
    assert d.judge == "Ахметов А.А."
    assert d.opponent == "организации"
    assert d.topic == "Общее имущество, паркинг"
    assert d.amounts.total == 0                    # сумма в отказной строке не «взыскана»
    assert {(c.law, c.article) for c in d.citations} == {("ГК", "654"), ("ГК", "541"), ("ГК", "543")}


def test_satisfied_but_rest_refused_is_partial_and_judge_court_from_signature_form():
    d = parse_decision(PARTIAL_TEXT)
    assert d.outcome == PARTIAL
    assert d.procedure == "упрощённое (письменное)"
    assert d.court == "Межрайонного суда по гражданским делам города Астаны"
    assert d.plaintiffs == ["объединение собственников имущества «Джамбула 1»"]
    assert d.amounts.principal == 3_740_430.81
    assert d.amounts.other_costs == 4_442          # «расходы по оплате исполнительной надписи»


def test_ruling_is_not_a_decision():
    d = parse_decision(RULING)
    assert d.doc_type == "определение"
    assert not d.is_decision


@pytest.mark.parametrize("text, expected", [
    ("Иск ОСИ – удовлетворить частично.", PARTIAL),
    ("Иск ОСИ частично удовлетворить.", PARTIAL),
    ("Иск ОСИ удовлетворить. В остальной части иска отказать.", PARTIAL),
    ("Иск ОСИ – удовлетворить. Взыскать 100 тенге.", SATISFIED),
    ("В удовлетворении иска ОСИ к ТОО – отказать.", REFUSED),
])
def test_classify_outcome(text, expected):
    assert classify_outcome(text) == expected


def test_expand_articles():
    assert _expand_articles("223-226, 267-4") == ["223", "224", "225", "226", "267-4"]
    assert _expand_articles("72,73") == ["72", "73"]
    assert _expand_articles("403–404") == ["403", "404"]
    assert _expand_articles("42-1") == ["42-1"]


def test_alias_with_typo_and_unresolved_reference():
    text = ("статьи 1 Закона «О жилищных отношениях» о (далее - Закон). "
            "Ещё статьи 8 Закона «О тестах». Затем пункта 8 статьи 31 Закона. И статьей 436 настоящего Кодекса.")
    cits, unresolved = extract_citations(text)
    assert Citation("Закон «О жилищных отношениях»", "31") in cits
    assert len(unresolved) == 1 and "436" in unresolved[0]


def test_split_parties_keeps_commas_inside_quotes():
    assert split_parties(["Адылов Равиль,", "Ким Анна Сергеевна, Ли Ван"]) == ["Адылов Равиль", "Ким Анна Сергеевна", "Ли Ван"]
    assert split_parties(['ТОО "Альфа, Бета"']) == ['ТОО "Альфа, Бета"']


def test_amounts_ignore_lines_without_vzyskat():
    a = extract_amounts(["Обязать ТОО передать документы.", "В возмещении расходов 350 000 тенге – отказать."])
    assert a.total == 0


def test_mask_and_judge_normalization():
    assert mask_person("Тестова Анна Борисовна") == "Т. А. Б."
    assert normalize_judge("Д.К.Жусупова") == "Жусупова Д.К."
    assert normalize_judge("А.Смаилов") == "Смаилов А."
    assert normalize_judge("Баймахан А. Ж.") == "Баймахан А.Ж."


# --- папка, дубли, статистика ------------------------------------------------------------------

def _save_docx(path, text):
    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    document.save(path)


def test_folder_reads_docx_and_misnamed_doc_dedups_and_excludes(tmp_path):
    _save_docx(tmp_path / "full.docx", DEBT)
    _save_docx(tmp_path / "short.doc", DEBT.split("МОТИВИРОВОЧНАЯ")[0] + "РЕШИЛ:\nИск – удовлетворить.\n")
    _save_docx(tmp_path / "ruling.docx", RULING)
    (tmp_path / "refusal.txt").write_text(REFUSAL, encoding="utf-8")
    (tmp_path / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4")

    result = analyze_folder(tmp_path)
    assert sorted(d.case_number for d in result.decisions) == ["7119-25-00-2/2222", "7520-25-00-2/1111"]
    kept = next(d for d in result.decisions if d.case_number == "7520-25-00-2/1111")
    assert kept.file == "full.docx"                       # из двух файлов дела взят полный
    reasons = {e.file: e.reason for e in result.excluded}
    assert "ruling.docx" in reasons and "short.doc" in reasons
    errors = dict(result.errors)
    assert "сохраните как .docx" in errors["old.doc"]
    assert "scan.pdf" in errors


def test_docx_table_text_is_read_in_order(tmp_path):
    document = docx.Document()
    document.add_paragraph("РЕШЕНИЕ")
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ["5 сентября 2025 года", "дело № 7514-25-00-2/27498", "город Алматы"]):
        cell.text = value
    path = tmp_path / "t.docx"
    document.save(path)
    assert read_text(path).splitlines()[-1] == "5 сентября 2025 года | дело № 7514-25-00-2/27498 | город Алматы"


def test_statistics():
    decisions = select_decisions([parse_decision(DEBT), parse_decision(REFUSAL), parse_decision(PARTIAL_TEXT)]).decisions
    rows = {r.label: r for r in outcome_table(decisions, side_group)}
    persons = rows["ОСИ — истец, против: физлица"]
    assert (persons.total, persons.won, persons.known) == (2, 2, 2)
    orgs = rows["ОСИ — истец, против: организации"]
    assert (orgs.total, orgs.won) == (1, 0)
    assert [osi_won(d) for d in decisions].count(False) == 1

    top = article_table(decisions)[0]
    assert top.decisions == 1
    money = money_stats(decisions)
    assert money.decisions == 2
    assert money.principal_max == 3_740_430.81


@pytest.mark.parametrize("claim, topic", [
    ("о признании недействительным протокола собрания в части избрания председателя ОСИ «Абая 1»",
     "Оспаривание решений собраний, актов и действий"),
    ("о признании незаконными действия по повторному предъявлению задолженности",
     "Оспаривание решений собраний, актов и действий"),
    ("о взыскании задолженности", "Взыскание задолженности по взносам и расходам на содержание"),
    ("об обязании предоставить документы", "Передача и предоставление документов, информации"),
    ("О возложении обязанности предоставить акт сверки", "Передача и предоставление документов, информации"),
    ("О продлении гарантийного срока Об обязании предоставить документы", "Устранение строительных дефектов"),
    ("о взыскании суммы", "Взыскание денежной суммы (предмет в решении не указан)"),
    ("о понуждении направлять счета, о взыскании расходов по оплате услуг представителя", "Другое"),
])
def test_classify_topic(claim, topic):
    from sud_parser.practice.extract import classify_topic
    assert classify_topic(claim) == topic
