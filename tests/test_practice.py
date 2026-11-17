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
    ("Иск Иванова И.И. к ОСИ «Дом» о возмещении ущерба оставить без удовлетворения.", REFUSED),
    ("Иск удовлетворить частично. В остальной части иск оставить без удовлетворения.", PARTIAL),
])
def test_classify_outcome(text, expected):
    assert classify_outcome(text) == expected


def test_amount_without_tenge_and_bank_costs():
    from sud_parser.practice.extract import extract_amounts
    a = extract_amounts([
        "Взыскать с ТОО «Ромашка» в пользу ОСИ «Дом» сумму ущерба в размере 12 940 285 (двенадцать миллионов "
        "девятьсот сорок тысяч двести восемьдесят пять) тенге, сумму уплаченной госпошлины в размере 390 175 "
        "(триста девяносто тысяч сто семьдесят пять).",
        "Взыскать с ИП «Тест» в пользу ОСИ «Дом» услуг почты в сумме 695 (шестьсот девяносто пять) тенге, "
        "услуг банка в сумме 765 (семьсот шестьдесят пять) тенге.",
    ])
    assert (a.principal, a.state_fee, a.other_costs) == (12_940_285, 390_175, 695 + 765)


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
    assert (persons.total, persons.won, persons.partly, persons.known) == (2, 1, 1, 2)
    orgs = rows["ОСИ — истец, против: организации"]
    assert (orgs.total, orgs.won) == (1, 0)
    assert [osi_won(d) for d in decisions].count(False) == 1

    top = article_table(decisions)[0]
    assert top.decisions == 1
    money = money_stats(decisions)
    assert money.decisions == 2
    assert money.principal_max == 3_740_430.81


def test_osi_result_partial_is_the_same_for_both_sides():
    from sud_parser.practice.analyze import LOST, PARTLY, WON, osi_result
    from sud_parser.practice.extract import Decision
    osi, person = "ОСИ «Дом»", "Иванов И.И."
    as_plaintiff = dict(plaintiffs=[osi], defendants=[person])
    as_defendant = dict(plaintiffs=[person], defendants=[osi])
    cases = [
        (as_plaintiff, SATISFIED, WON), (as_plaintiff, PARTIAL, PARTLY), (as_plaintiff, REFUSED, LOST),
        (as_defendant, REFUSED, WON), (as_defendant, PARTIAL, PARTLY), (as_defendant, SATISFIED, LOST),
    ]
    for sides, outcome, expected in cases:
        assert osi_result(Decision(file="", outcome=outcome, **sides)) == expected
    assert osi_result(Decision(file="", outcome=SATISFIED, plaintiffs=[person], defendants=["ТОО «Строй»"])) is None



@pytest.mark.parametrize("claim, topic", [
    ("о признании недействительным протокола собрания в части избрания председателя ОСИ «Абая 1»",
     "Оспаривание решений собраний (протоколов)"),
    ("о признании незаконными действия по повторному предъявлению задолженности, об обязании внести "
     "изменения в бухгалтерскую документацию", "Оспаривание действий и актов (ОСИ, застройщика, госорганов)"),
    ("о признании незаконным бездействия и истребовании документации",
     "Передача и предоставление документов, информации"),
    ("о понуждении передать документы, а также копии протоколов общего собрания",
     "Передача и предоставление документов, информации"),
    ("1.Об установлении факта трудовых отношений 2.О взыскании задолженности по заработной плате",
     "Трудовые споры"),
    ("о возмещении ущерба, причинённого затоплением квартиры", "Возмещение ущерба (затопление и т. п.)"),
    ("о признании исполнительной надписи не подлежащей исполнению", "Исполнительная надпись нотариуса"),
    ("о взыскании расходов по оплате услуг нотариуса за совершение исполнительной надписи",
     "Исполнительная надпись нотариуса"),
    ("О принудительной ликвидации и снятии всех обременений", "Принудительная ликвидация ОСИ"),
    ("об освобождении недвижимого имущества от ареста", "Освобождение имущества от ареста"),
    ("О взыскании суммы долга за содержание многоквартирного жилого дома.",
     "Взыскание задолженности по взносам и расходам на содержание"),
    ("Тұрғын үй кешені тұрғындарының жиналысы хаттамасының күшін жою туралы",
     "Оспаривание решений собраний (протоколов)"),
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


def test_split_amounts_direction_total_and_each():
    from sud_parser.practice.extract import FROM_OSI, OTHER, TO_OSI, split_amounts
    lines = [
        "Взыскать с Иванова И.И. в пользу Объединения собственников имущества «Дом» задолженность "
        "в размере 20 000 тенге, возврат уплаченной госпошлины в размере 600 тенге, всего на сумму 20 600 (двадцать "
        "тысяч шестьсот) тенге.",
        "Взыскать с объединения собственников имущества «Дом» в пользу Петрова П.П., Сидоровой С.С. судебные "
        "расходы по оплате государственной пошлины в размере 3 692 (три тысячи) тенге каждому.",
        "Взыскать с Иванова И.И. в пользу Петрова П.П. расходы по госпошлине 1 846 тенге.",
    ]
    out = split_amounts(lines, osi_plaintiff=True)
    assert out[TO_OSI].principal == 20_000          # «всего 20 600» не добавляется второй раз
    assert out[TO_OSI].state_fee == 600
    assert out[FROM_OSI].state_fee == 7_384         # 3 692 × 2 получателя
    assert out[OTHER].state_fee == 1_846


def test_citation_variants():
    text = (
        "согласно статье 43 ЗРК «О жилищных отношениях» решение недействительно. "
        "В силу статьи 43 Республики Казахстан «О жилищных отношениях» (далее - Закон). "
        "Руководствуясь статьями 48, части 3 статьи 169 ГПК, а также статьей 196 Гражданского "
        "процессуального права (далее – ГПК). Нормативное постановление Верховного Суда Республики "
        "Казахстан «О судебном решении» по статье 50 Закона."
    )
    cits, unresolved = extract_citations(text)
    got = {(c.law, c.article) for c in cits}
    assert ("Закон «О жилищных отношениях»", "43") in got
    assert ("Закон «О жилищных отношениях»", "50") in got
    assert {("ГПК", "48"), ("ГПК", "169"), ("ГПК", "196")} <= got
    assert unresolved == []


RTF_SAMPLE = (
    rb"{\rtf1\ansi\ansicpg1251\deff0{\fonttbl{\f0\fcharset204 Times New Roman;}{\f1\fcharset0 Arial;}}"
    rb"{\colortbl;\red0\green0\blue0;}{\*\generator Msftedit;}"
    rb"\pard\qc\f0 \'d0\'c5\'d8\'c5\'cd\'c8\'c5\par"
    rb"\'c8\'cc\'c5\'cd\'c5\'cc \'d0\'c5\'d1\'cf\'d3\'c1\'cb\'c8\'ca\'c8 \'ca\'c0\'c7\'c0\'d5\'d1\'d2\'c0\'cd\par"
    rb"\uc1\u1076?\u1077?\u1083?\u1086? \'b9 7119-25-00-2/7227\par"
    rb"\trowd\intbl \'c8\'d1\'d2\'c5\'d6\cell \'ce\'d1\'c8 \'ab\'c4\'ee\'ec\'bb\cell\row"
    rb"\f1 Total\tab end\par}"
)


def test_rtf_reader(tmp_path):
    from sud_parser.practice.reader import read_text, rtf_to_text
    text = rtf_to_text(RTF_SAMPLE)
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines[0] == "РЕШЕНИЕ"
    assert lines[1] == "ИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН"
    assert lines[2] == "дело № 7119-25-00-2/7227"
    assert lines[3] == "ИСТЕЦ | ОСИ «Дом»"
    assert lines[4] == "Total\tend"
    assert "Times" not in text and "Msftedit" not in text
    # .doc, внутри которого RTF, читается так же
    p = tmp_path / "решение.doc"
    p.write_bytes(RTF_SAMPLE)
    assert read_text(p).splitlines()[0] == "РЕШЕНИЕ"


def test_split_amounts_equal_shares():
    from sud_parser.practice.extract import FROM_OSI, OTHER, split_amounts
    lines = [
        "Взыскать с объединения собственников имущества «Талисман», Иванова И.И., Петрова П.П., "
        "Сидорова С.С., Козлова К.К. в пользу Смирновой С.С. расходы по оплате услуг представителя "
        "в размере 200 000 (двести тысяч) тенге в долевом порядке, в равных долях.",
        "Взыскать солидарно с ОСИ «Дом» и Иванова И.И. в пользу Петрова П.П. госпошлину 1 000 тенге.",
    ]
    out = split_amounts(lines, osi_plaintiff=False)
    assert out[FROM_OSI].lawyer == 40_000      # 200 000 / 5 плательщиков
    assert out[OTHER].lawyer == 160_000
    assert out[FROM_OSI].state_fee == 1_000    # солидарно: ОСИ отвечает за всю сумму


def test_this_code_refers_to_code_quoted_before():
    text = ("Согласно статье 271 Гражданского кодекса Республики Казахстан обязательства возникают из "
            "оснований, указанных в статье 7 настоящего Кодекса. Пунктом 5 статьи 42-1 установлено, что …")
    cits, unresolved = extract_citations(text)
    assert Citation("ГК", "7") in cits
    assert len(unresolved) == 1 and "42-1" in unresolved[0]   # закон не назван — не угадываем


COUNTER_TEXT = r"""РЕШЕНИЕ
ИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН
26 июня 2025 года		№ 7514-25-00-2\4027         город Алматы
Бостандыкский районный суд города Алматы в составе:
председательствующего, судьи Тестов Т.Т.
ИСТЕЦ:
Тестова Анна Борисовна
ОТВЕТЧИК:
объединение собственников имущества «Тест»
ТРЕБОВАНИЯ ИСТЦА:
О признании недействительным решения собрания
ИСТЕЦ ПО ВСТРЕЧНОМУ ИСКУ:
объединение собственников имущества «Тест»
РЕЗОЛЮТИВНАЯ ЧАСТЬ
Руководствуясь статьями 223-226 ГПК, суд РЕШИЛ: В удовлетворении иска Тестовой А.Б. к ОСИ «Тест» отказать.
Встречный иск объединения собственников имущества «Тест» - удовлеторить частично.
Взыскать с Тестовой А.Б. в пользу объединения собственников имущества «Тест» задолженность в размере 36 967 тенге.
В остальной части встречного иска отказать.
Председательствующий судья Тестов Т.Т.
"""


def test_counterclaim_inline_operative_and_backslash_number():
    d = parse_decision(COUNTER_TEXT, "x.docx")
    assert d.case_number == "7514-25-00-2/4027"
    assert d.outcome == REFUSED                      # основной иск жителя — отказ, ОСИ выиграло
    assert d.counter_outcome == PARTIAL              # встречный иск ОСИ — частично («удовлеторить» — опечатка)
    assert d.amounts.principal == 36_967
    assert d.osi_role == "ответчик"
    assert "резолютивная часть («РЕШИЛ:») не найдена" not in d.warnings


def test_header_variants():
    text = COUNTER_TEXT.replace("26 июня", "19 c\u0435нтября").replace(
        "ТРЕБОВАНИЯ ИСТЦА:", "ТРЕТЬИ ЛИЦА, НЕ ЗАЯВЛЯЮЩИЕ САМОСТОЯТЕЛЬНЫХ\nТРЕБОВАНИЙ НА ПРЕДМЕТ СПОРА:\n"
        "ГУ «Управление жилья»\nЗАЯВЛЕННОЕ ТРЕБОВАНИЕ:")
    d = parse_decision(text, "x.docx")
    assert str(d.date) == "2025-09-19"                       # латинская «c» в «cентября»
    assert d.claim.startswith("О признании недействительным")
    assert d.third_parties == ["ГУ «Управление жилья»"]


def test_breakdown_per_payer_not_double_counted():
    from sud_parser.practice.extract import TO_OSI, split_amounts
    total_then_each = ["Взыскать с Иванова И.И., Петрова П.П., Сидорова С.С., Козлова К.К. в пользу ОСИ «Дом» "
                       "представительские расходы в размере 500 000 (пятьсот тысяч) тенге, по 125 000 (сто двадцать "
                       "пять тысяч) тенге с каждого."]
    assert split_amounts(total_then_each, osi_plaintiff=False)[TO_OSI].lawyer == 500_000
    only_each = ["Взыскать с Иванова И.И., Петрова П.П. в пользу ОСИ «Дом» расходы на представителя "
                 "по 100 000 тенге с каждого."]
    assert split_amounts(only_each, osi_plaintiff=False)[TO_OSI].lawyer == 200_000


def test_tiyn_after_tenge_and_osi_on_both_sides():
    from sud_parser.practice.extract import OTHER, TO_OSI, split_amounts
    out = split_amounts(["Взыскать с Иванова И.И. в пользу ОСИ «Дом» задолженность в размере 671 874 "
                         "(шестьсот семьдесят одна тысяча) тенге 18 тиын."], osi_plaintiff=True)
    assert out[TO_OSI].principal == 671_874.18
    out = split_amounts(["Взыскать с кооператива собственников имущества «Акбас» в пользу объединения "
                         "собственников имущества «Центр» расходы по госпошлине 1 966 тенге."], osi_plaintiff=True)
    assert out[OTHER].state_fee == 1_966 and out[TO_OSI].total == 0


KZ_TEXT = r"""ҚАЗАҚСТАН РЕСПУБЛИКАСЫНЫҢ АТЫНАН
ШЕШІМ
2025 жылғы 17 наурыз         №5242-24-00-2/99999 іс          Шымкент қаласы
Шымкент қаласының азаматтық істер жөніндегі ауданаралық сотының құрамында:
төрағалық етуші судья Т.Т.Тестов,
ашық сот отырысында қойылған талап бойынша азаматтық істі қарады:
ТАЛАП ҚОЮШЫЛАР:
Анна Борисовна Тестова, Пётр Петрович Петров
ЖАУАПКЕР:
«Тест Парк» мүлік меншік иелерінің бірлестігі
ТАЛАП ҚОЮШЫЛАРДЫҢ ТАЛАБЫ:
Тұрғын үй кешені тұрғындарының жиналысы хаттамасының күшін жою туралы.
УӘЖДЕУ БӨЛІГІ:
Қазақстан Республикасының «Тұрғын үй қатынастары туралы» Заңының (бұдан әрі - Заң) 42-бабына сәйкес.
Заңның 42-1-бабының 5-тармағына сай, жиналыс заңды. АК-нің 350, 351-баптарына сәйкес.
Согласно осы Кодекстiң 9-бабының 4-тармағы.
ҚАРАР БӨЛІГІ:
АПК-нің 223-226-баптарын басшылыққа алып, сот
Ш Е Ш І М Е Т Т I :
Талап қоюшылардың талап қоюын қанағаттандырудан толығымен бас тартылсын.
Талап қоюшылар Анна Борисовна Тестовадан, Пётр Петрович Петровтан әр қайсысынан жауапкер «Тест Парк» мүлік меншік иелерінің бірлестігінің пайдасына 100 000 (жүз мың) теңге өкілдің қызметі үшін төлеген шығыны өндірілсін.
Анна Борисовна Тестовадан мемлекет пайдасына 4 604 (төрт мың) теңге 28 (жиырма сегіз) тиын мемлекеттік баж өндірілсін.
Шешімге наразы жақ бір ай ішінде апелляциялық шағым беруге құқылы.
Судья                                                Т.Т.Тестов
"""


def test_kazakh_decision():
    d = parse_decision(KZ_TEXT, "kz.docx")
    assert d.doc_type == "решение"
    assert d.case_number == "5242-24-00-2/99999"
    assert str(d.date) == "2025-03-17"
    assert d.city == "Шымкент"
    assert d.court.startswith("Шымкент қаласының азаматтық істер")
    assert d.judge == "Тестов Т.Т."
    assert d.procedure == "судебное заседание"
    assert len(d.plaintiffs) == 2 and d.osi_role == "ответчик" and d.opponent == "физлица"
    assert d.topic == "Оспаривание решений собраний (протоколов)"
    assert d.outcome == REFUSED                      # «қанағаттандырудан толығымен бас тартылсын»
    assert d.amounts.lawyer == 200_000               # 100 000 × 2 плательщика («әр қайсысынан»)
    assert d.other_awards.state_fee == 4_604.28      # в доход государства, с тиынами
    got = {(c.law, c.article) for c in d.citations}
    assert ("Закон «О жилищных отношениях»", "42") in got     # казахское название -> русское
    assert ("Закон «О жилищных отношениях»", "42-1") in got   # «Заңның» по сокращению «(бұдан әрі - Заң)»
    assert {("ГК", "350"), ("ГК", "351"), ("ГК", "9"), ("ГПК", "223"), ("ГПК", "226")} <= got
    assert d.unresolved_citations == []


@pytest.mark.parametrize("op, outcome", [
    ("Талап қоюы қанағаттандырылсын.", SATISFIED),
    ("Талап қоюы ішінара қанағаттандырылсын.", PARTIAL),
    ("Талап қоюы қанағаттандырылсын. Қалған талаптарын қанағаттандырудан бас тартылсын.", PARTIAL),
    ("Талап арызы қанағаттандырусыз қалдырылсын.", REFUSED),
])
def test_kazakh_outcomes(op, outcome):
    assert classify_outcome(op) == outcome


def test_kazakh_award_to_cooperative_without_paidasyna():
    from sud_parser.practice.extract import TO_OSI, split_amounts
    out = split_amounts(["Жауапкер Анна Тестовадан коммуналдық қызметтерге берешек 181 000 (жүз) теңге "
                         "«Жаңақала» пәтер иелері кооперативіне өндірілсін."], osi_plaintiff=False)
    assert out[TO_OSI].principal == 181_000


def test_analyze_folders_counts_case_once(tmp_path):
    from sud_parser.practice.analyze import analyze_folders
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "debt.txt").write_text(DEBT, encoding="utf-8")
    (b / "debt.txt").write_text(DEBT, encoding="utf-8")       # то же дело во второй папке
    (b / "refusal.txt").write_text(REFUSAL, encoding="utf-8")
    result = analyze_folders([a, b])
    assert result.files_total == 3
    assert len(result.decisions) == 2
    assert [e.file for e in result.excluded] == ["b/debt.txt"]


def test_court_after_date_on_same_line():
    text = ("Р Е Ш Е Н И Е\nИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН\n"
            "26 августа 2025 года\tдело № 7142-25-00-2/99999\tгород Астана Судья Межрайонного суда по гражданским "
            "делам города Астаны\nТестова А.К., рассмотрев в порядке упрощенного производства гражданское дело:\n"
            "ИСТЕЦ:\nИванов Иван Иванович\nОТВЕТЧИК:\nОбъединение собственников имущества «Дом»\n"
            "ТРЕБОВАНИЯ ИСТЦА:\nо взыскании суммы ущерба\nРЕЗОЛЮТИВНАЯ ЧАСТЬ:\nсудья\nРЕШИЛ:\nИск удовлетворить.\n")
    d = parse_decision(text)
    assert d.court == "Межрайонного суда по гражданским делам города Астаны"
    assert "суд не найден" not in d.warnings
