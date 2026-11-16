"""Разбор текста судебного решения в структуру.

Правила написаны по настоящим решениям судов РК по гражданским делам (2025 год), скачанным
из «Банка судебных актов» portal-sot.kz. Типичное решение устроено так:

    РЕШЕНИЕ / ИМЕНЕМ РЕСПУБЛИКИ КАЗАХСТАН
    <дата>  дело №7514-25-00-2/27138  город Алматы      (иногда эта строка внизу, в таблице)
    <суд> в составе судьи ...
    ИСТЕЦ: ...  ОТВЕТЧИК(И): ...  ТРЕБОВАНИЯ ИСТЦА: ...
    ОПИСАТЕЛЬНАЯ / МОТИВИРОВОЧНАЯ ЧАСТЬ (ссылки на статьи законов)
    РЕШИЛ: Иск ... – удовлетворить / удовлетворить частично / В удовлетворении иска ... отказать.
           Взыскать с ... в размере ... тенге.

Принцип: то, что не удалось определить уверенно, остаётся пустым и попадает в предупреждения.
Ничего не угадывается.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# --- исходы ---------------------------------------------------------------------------------
SATISFIED = "удовлетворён"
PARTIAL = "удовлетворён частично"
REFUSED = "отказано"
NO_CONSIDERATION = "оставлен без рассмотрения"
TERMINATED = "производство прекращено"
UNKNOWN = "не определён"
OUTCOMES = (SATISFIED, PARTIAL, REFUSED, NO_CONSIDERATION, TERMINATED, UNKNOWN)

# --- виды сторон ----------------------------------------------------------------------------
OSI, ORG, PERSON = "ОСИ", "организация", "физлицо"

PROCEDURAL_LAWS = {"ГПК"}

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
CASE_NO_RE = re.compile(r"(\d{4}-\d{2}-\d{2}-[0-9A-Za-zА-Яа-я]{1,3}/\d+)")
DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\s*(?:года?\b|г\.)", re.I)  # «2025 года», «2025год», «2025 г.»

OSI_RE = re.compile(
    r"объединени\w*\s+собственник|\bОСИ\b|\bП?КСК\b|кооператив\w*\s+собственник|простое\s+товариществ",
    re.I,
)
ORG_RE = re.compile(
    r"[«\"]|\bТОО\b|\bАО\b|\bНАО\b|\bИП\b|\bГУ\b|\bРГП\b|\bГКП\b|товариществ|обществ|учреждени|"
    r"предприяти|корпораци|компани|филиал|акимат|департамент|управлени|министерств|комитет|банк",
    re.I,
)

# Заголовки блоков решения (сравниваются без пробелов: «Р Е Ш И Л» == «РЕШИЛ»).
HEADINGS = (
    "ИСТЕЦ", "ИСТЦЫ", "ОТВЕТЧИК", "ТРЕБОВАНИ", "ТРЕТЬ", "ВСУДЕУЧАСТВОВАЛ", "ОПИСАТЕЛЬН",
    "МОТИВИРОВОЧН", "РЕЗОЛЮТИВН", "РЕШИЛ", "СУДРЕШИЛ", "УСТАНОВИЛ", "ПОСТАНОВИЛ", "ОПРЕДЕЛИЛ",
    "ЗАЯВИТЕЛ", "ЗАИНТЕРЕСОВАНН", "ПРОКУРОР", "ПРЕДСТАВИТЕЛ",
)
OPERATIVE = ("РЕШИЛ", "СУДРЕШИЛ", "ПОСТАНОВИЛ", "ОПРЕДЕЛИЛ")

# Строки резолютивной части, которые разъясняют порядок обжалования, а не решают спор.
BOILERPLATE_RE = re.compile(
    r"^(на решение|на определение|ответчики? вправе|заявление подается|апелляционн|"
    r"решение (суда )?может быть обжаловано|решение суда может|решение может быть обжаловано)",
    re.I,
)

TOPICS = (
    # Первым: иначе «признать незаконным начисление задолженности» попало бы в «долги»,
    # а «протокол … ОСИ «…» … общего имущества» — в «общее имущество».
    ("Оспаривание решений собраний, актов и действий",
     re.compile(r"недействительн|незаконн|отмен\w* протокол|оспарива", re.I)),
    ("Взыскание задолженности по взносам и расходам на содержание",
     re.compile(r"задолженн|расход\w* на содержание|взнос|неустойк", re.I)),
    ("Устранение строительных дефектов", re.compile(r"дефект|недостат|устранить нарушени|гаранти", re.I)),
    ("Передача и предоставление документов, информации",
     re.compile(r"документ|сведени|информаци|акт\w* сверки|отч[её]т", re.I)),
    ("Общее имущество, паркинг", re.compile(r"паркинг|общ\w+ имуществ", re.I)),
    ("Договорные споры", re.compile(r"договор", re.I)),
    # В коротких решениях пишут только «о взыскании суммы» — что за сумма, из текста не видно.
    ("Взыскание денежной суммы (предмет в решении не указан)",
     re.compile(r"^\W*о\s+взыскании\s+(?:денежной\s+)?суммы\W*$", re.I)),
)


@dataclass
class Amounts:
    """Суммы, которые суд постановил взыскать (тенге), по видам."""
    principal: float = 0.0    # основной долг / сумма требования
    penalty: float = 0.0      # неустойка, пеня
    state_fee: float = 0.0    # госпошлина
    lawyer: float = 0.0       # услуги представителя
    other_costs: float = 0.0  # почтовые, экспертиза и т. п.

    @property
    def total(self) -> float:
        return self.principal + self.penalty + self.state_fee + self.lawyer + self.other_costs

    def add(self, kind: str, value: float) -> None:
        setattr(self, kind, round(getattr(self, kind) + value, 2))


@dataclass(frozen=True)
class Citation:
    law: str      # «ГК», «ГПК», «Закон «О жилищных отношениях»»
    article: str  # «50», «42-1»

    @property
    def procedural(self) -> bool:
        return self.law in PROCEDURAL_LAWS


@dataclass
class Decision:
    file: str
    doc_type: str = ""
    case_number: str = ""
    date: date | None = None
    city: str = ""
    court: str = ""
    judge: str = ""
    procedure: str = ""
    plaintiffs: list[str] = field(default_factory=list)
    defendants: list[str] = field(default_factory=list)
    third_parties: list[str] = field(default_factory=list)
    claim: str = ""
    topic: str = ""
    outcome: str = UNKNOWN
    outcome_text: str = ""
    amounts: Amounts = field(default_factory=Amounts)        # взыскано в пользу ОСИ
    osi_pays: Amounts = field(default_factory=Amounts)       # взыскано с ОСИ
    other_awards: Amounts = field(default_factory=Amounts)   # между другими участниками
    obligations: int = 0
    citations: list[Citation] = field(default_factory=list)
    resolutions: list[str] = field(default_factory=list)
    unresolved_citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    text_length: int = 0

    @property
    def is_decision(self) -> bool:
        return "решение" in self.doc_type

    @property
    def osi_role(self) -> str:
        roles = []
        if any(party_kind(p) == OSI for p in self.plaintiffs):
            roles.append("истец")
        if any(party_kind(p) == OSI for p in self.defendants):
            roles.append("ответчик")
        return " и ".join(roles) or "нет"

    @property
    def opponent(self) -> str:
        """С кем спорит ОСИ: физлица, организации или смешанный состав."""
        if self.osi_role == "истец":
            others = self.defendants
        elif self.osi_role == "ответчик":
            others = self.plaintiffs
        else:
            return ""
        kinds = {party_kind(p) for p in others} - {OSI}
        if kinds == {PERSON}:
            return "физлица"
        if kinds == {ORG}:
            return "организации"
        if kinds:
            return "смешанный состав"
        return ""


# --- вспомогательные функции -----------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"[ \t   ]+", " ", text).strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def party_kind(name: str) -> str:
    if OSI_RE.search(name):
        return OSI
    if ORG_RE.search(name):
        return ORG
    return PERSON


def mask_person(name: str) -> str:
    """«Тестова Анна Борисовна» -> «Т. А. Б.»: в отчёт не попадают полные ФИО."""
    words = [w for w in re.split(r"\s+", name) if w]
    return " ".join(f"{w[0]}." for w in words[:3]) if words else ""


def display_party(name: str) -> str:
    return f"{PERSON} {mask_person(name)}" if party_kind(name) == PERSON else name


def _parse_money(number: str, fraction: str | None) -> float:
    value = float(re.sub(r"\D", "", number))
    if fraction:
        value += int(fraction.ljust(2, "0")) / 100
    return value


def _heading(line: str) -> tuple[str, str] | None:
    """Если строка — заголовок блока («ОТВЕТЧИКИ: ...»), вернуть (ключ, текст после двоеточия)."""
    head, _, rest = line.partition(":")
    if len(head) > 140:
        return None
    letters = [c for c in head if c.isalpha()]
    if not letters or any(c.islower() for c in letters):
        return None
    key = _compact(head)
    for h in HEADINGS:
        if key.startswith(h):
            return key, rest.strip()
    return None


def _sections(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Шапка (до первого заголовка) и блоки [(заголовок, строки)]."""
    header: list[str] = []
    blocks: list[tuple[str, list[str]]] = []
    for line in lines:
        h = _heading(line)
        if h:
            blocks.append((h[0], [h[1]] if h[1] else []))
        elif blocks:
            blocks[-1][1].append(line)
        else:
            header.append(line)
    return header, blocks


def _block(blocks, *prefixes: str) -> list[str] | None:
    for key, lines in blocks:
        if key.startswith(prefixes):
            return lines
    return None


def _split_outside_quotes(text: str) -> list[str]:
    parts, buf, depth, straight = [], [], 0, False
    for ch in text:
        if ch == "«":
            depth += 1
        elif ch == "»":
            depth = max(0, depth - 1)
        elif ch == '"':
            straight = not straight
        if ch in ",;" and depth == 0 and not straight:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def split_parties(lines: list[str]) -> list[str]:
    """Строки блока «ОТВЕТЧИКИ:» -> список сторон.

    Название в кавычках может переноситься на следующую строку, а внутри кавычек бывают запятые
    («ЖК Рио Де Жанейро, ул. Бейбарыс Султан, дом 25/1») — такие запятые не разделяют стороны.
    """
    merged, buf = [], ""
    for line in (_norm(l) for l in lines):
        if not line:
            continue
        buf = f"{buf} {line}" if buf else line
        if buf.count("«") > buf.count("»") and len(buf) < 400:
            continue
        merged.append(buf)
        buf = ""
    if buf:
        merged.append(buf)

    parties: list[str] = []
    for item in merged:
        item = re.sub(r"\([^()]*\)", " ", item)  # «(далее – истец)», «(далее – ОСИ)»
        for part in _split_outside_quotes(item):
            part = _norm(part).strip(" ,;.:–-")
            if not part:
                continue
            continues_prev = part[0].islower() and not re.match(
                r"(объединени|товариществ|акционерн|некоммерческ|государствен|индивидуальн)", part, re.I
            )
            if parties and continues_prev:  # «..., в лице филиала ...»
                parties[-1] += ", " + part
            else:
                parties.append(part)
    return parties


# --- статьи законов --------------------------------------------------------------------------

ARTICLE_RE = re.compile(
    r"стат(?:ья|ьи|ьей|ью|ье|ьям|ьями|ьях|ей)\s+"
    r"(\d+(?:\s*[-–]\s*\d+)?(?:\s*(?:,|\bи\b)\s*\d+(?:\s*[-–]\s*\d+)?)*)",
    re.I,
)
# «Закон РК «…»», «ЗРК «…»».
LAW_HEAD = r"(?:Закон\w*|ЗРК)\s+(?:Республики\s+Казахстан\s+|РК\s+)?(?:от\s[^«]{0,40}?)?"
LAW_TITLE_RE = re.compile(LAW_HEAD + r"«([^»]{3,200})»", re.I)
# Сразу после номера статьи слово «Закон» иногда пропущено: «статьи 43 Республики Казахстан «…»».
# Только здесь: в остальном тексте так же пишут названия постановлений Верховного суда.
LAW_AFTER_ARTICLE_RE = re.compile(r"(?:" + LAW_HEAD + r"|Республики\s+Казахстан\s+)«([^»]{3,200})»", re.I)
ALIAS_RE = re.compile(
    LAW_HEAD + r"«([^»]{3,200})»\s*"
    r"(?:[^\s(]{1,3}\s*)?"  # опечатки вида «…отношениях» о (далее - Закон)
    r"\(\s*далее\s*[-–—]?\s*(?:по\s+тексту\s*[-–—]?\s*)?([^)]{1,30}?)\s*\)",
    re.I,
)
CODES = (
    ("ГПК", re.compile(r"(?:ГПК\b|Гражданск\w*\s+процессуальн\w*\s+(?:[Кк]одекс|прав))")),  # «…права» — опечатка в решениях
    ("ГК", re.compile(r"(?:ГК\b|Гражданск\w*\s+[Кк]одекс)")),
    ("НК", re.compile(r"(?:НК\b|Налогов\w*\s+[Кк]одекс)")),
    ("ЗК", re.compile(r"(?:ЗК\b|Земельн\w*\s+[Кк]одекс)")),
    ("АППК", re.compile(r"(?:АППК\b|Административн\w*\s+процедурн)")),
    ("КоАП", re.compile(r"(?:КоАП\b|Кодекс\w*\s+.{0,40}?об\s+административных\s+правонарушениях)")),
)
RESOLUTION_RE = re.compile(
    r"нормативн\w*\s+постановлени\w*\s+Верховного\s+Суда[^«]{0,160}?«([^»]{3,200})»", re.I
)


def _law_title(title: str) -> str:
    title = _norm(title).split(". ")[0]  # «О жилищных отношениях. Решение принято» — кавычка не закрыта
    return f"Закон «{title[0].upper()}{title[1:]}»"


def _expand_articles(numbers: str) -> list[str]:
    """«223-226, 267-4» -> 223, 224, 225, 226, 267-4.

    Дефис бывает диапазоном (223-226) и частью номера (42-1, 267-4): если второе число меньше
    первого — это номер статьи с дефисом.
    """
    result: list[str] = []
    for token in re.split(r"\s*(?:,|\bи\b)\s*", numbers):
        token = re.sub(r"\s*[-–]\s*", "-", token.strip())
        if not token:
            continue
        if "-" in token:
            a, b = (int(x) for x in token.split("-", 1))
            if b > a and b - a <= 20:
                result.extend(str(n) for n in range(a, b + 1))
            elif b > a:
                result.extend([str(a), str(b)])
            else:
                result.append(f"{a}-{b}")
        else:
            result.append(str(int(token)))
    return result


CHAINED_RE = re.compile(  # «статьи 2 и пункта 1 статьи 50 Закона», «статьи 48, части 3 статьи 169 ГПК»
    r"(?:и\s+)?(?:(?:пункт|част|подпункт)\w*\s+[\d\-]+\s+)*стат\w*\s+[\d\s,\-–и]+?\s*(?=[А-ЯЁA-Z])"
)


def _resolve_law(window: str, aliases: dict[str, str], bare_law: str | None) -> str | None:
    for name, rx in CODES:
        if rx.match(window):
            return name
    tm = LAW_AFTER_ARTICLE_RE.match(window)
    if tm:
        return _law_title(tm.group(1))
    for alias in sorted(aliases, key=len, reverse=True):
        if re.match(re.escape(alias) + r"(?![А-Яа-яЁё])", window):
            return aliases[alias]
    # «настоящего Закона» встречается в цитатах из закона и означает тот же закон.
    if re.match(r"(?:настоящего\s+)?Закон\w*\b", window):
        return bare_law
    return None


def extract_citations(text: str) -> tuple[list[Citation], list[str]]:
    """Статьи законов, на которые ссылается решение, и фрагменты ссылок, закон которых не определён."""
    aliases: dict[str, str] = {}
    for m in ALIAS_RE.finditer(text):
        alias = m.group(2).strip(" «»\"'")
        if alias:
            aliases[alias] = _law_title(m.group(1))
    titles = {_law_title(m.group(1)) for m in LAW_TITLE_RE.finditer(text)}
    bare_law = aliases.get("Закон") or (next(iter(titles)) if len(titles) == 1 else None)

    found: dict[Citation, None] = {}
    unresolved: list[str] = []
    for m in ARTICLE_RE.finditer(text):
        window = text[m.end(): m.end() + 220].lstrip(" ,.;:\t\n")
        law = _resolve_law(window, aliases, bare_law)
        if law is None:
            # «статьи 2 и пункта 1 статьи 50 Закона ...» — закон указан после второй статьи.
            chained = CHAINED_RE.match(window)
            if chained:
                law = _resolve_law(window[chained.end():], aliases, bare_law)
        if law is None:
            unresolved.append(_norm(text[m.start(): m.end() + 60]))
            continue
        for article in _expand_articles(m.group(1)):
            found[Citation(law, article)] = None
    return list(found), unresolved


# --- исход и суммы ---------------------------------------------------------------------------

def classify_outcome(operative: str) -> str:
    op = operative.lower()
    partial = re.search(r"удовлетворить\s+частично|частично\s+удовлетворить", op)
    satisfy = re.search(r"\bудовлетворить\b", op)
    rest_refused = re.search(r"остальной\s+части[^.]*?отказать|отказать[^.]*?остальной\s+части", op)
    refused = re.search(r"\bотказать\b", op)
    if partial or (satisfy and rest_refused):
        return PARTIAL
    if satisfy:
        return SATISFIED
    if refused:
        return REFUSED
    if re.search(r"без\s+рассмотрения", op):
        return NO_CONSIDERATION
    if re.search(r"производство[^.]*прекратить|прекратить\s+производство", op):
        return TERMINATED
    return UNKNOWN


# «… тенге», а иногда без слова «тенге»: «50435,68 (прописью) 68 тиын».
MONEY_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[.,](\d{1,2}))?(?!\d)"
    r"\s*(?:тенге|тг\b|(?<=\s)(?=\d{1,2}\s*тиын))",
    re.I,
)
MONEY_KINDS = (
    ("state_fee", re.compile(r"пошлин", re.I)),
    ("lawyer", re.compile(r"представител|юридическ\w* (?:услуг|помощ)", re.I)),
    ("penalty", re.compile(r"неустойк|\bпен[еиьяю]", re.I)),
    ("other_costs", re.compile(r"почтов|нотариал|эксперт|издерж|транспортн|курьер", re.I)),
)
PRINCIPAL_RE = re.compile(r"задолж|долг|накоплен|взнос|капитальн", re.I)
COSTS_RE = re.compile(r"расход|оплат", re.I)


def _money_kind(context: str) -> str:
    kind = next((k for k, rx in MONEY_KINDS if rx.search(context)), None)
    if kind:
        return kind
    # «расходы по оплате 2594 тенге» без уточнения — это судебные расходы, а не долг.
    if COSTS_RE.search(context) and not PRINCIPAL_RE.search(context):
        return "other_costs"
    return "principal"


# «…, всего 20 600 тенге» — это сумма уже перечисленного, второй раз её не считаем.
TOTAL_RE = re.compile(r"\b(?:всего|итого|в\s+общей\s+сумме|на\s+общую\s+сумму)\b", re.I)
PAYER_PAYEE_RE = re.compile(r"\bвзыскать\b(?P<payer>.*?)\bв\s+пользу\b(?P<payee>.*)", re.I)
# Где кончается название получателя и начинается «за что»: «… в пользу ОСИ «Х» задолженность …».
PAYEE_END_RE = re.compile(
    r"\s(?:сумм|задолж|расход|судебн|государствен|госпошлин|оплат|возврат|нотариал|почтов|неустойк|"
    r"пен[яиюе]\b|услуг|представител|уплаченн|\d)", re.I)

TO_OSI, FROM_OSI, OTHER = "в пользу ОСИ", "с ОСИ", "между другими участниками"


def _award_lines(operative_lines: list[str]):
    """Строки «Взыскать …» без сумм прописью в скобках."""
    for line in operative_lines:
        if not re.search(r"\bвзыскать\b", line, re.I):
            continue
        clean = line
        while re.search(r"\([^()]*\)", clean):
            clean = re.sub(r"\([^()]*\)", " ", clean)
        yield _norm(clean)


def _line_amounts(clean: str) -> Amounts:
    amounts = Amounts()
    for fragment in re.split(r";|,\s+(?=[^\d\s])", clean):
        prev_end = 0
        for m in MONEY_RE.finditer(fragment):
            context = fragment[prev_end:m.start()]
            prev_end = m.end()
            if TOTAL_RE.search(context):
                continue
            amounts.add(_money_kind(context), _parse_money(m.group(1), m.group(2)))
    return amounts


def _each_multiplier(clean: str) -> int:
    """«… в пользу А, Б, В … по 3 692 тенге каждому» — сумма на каждого получателя."""
    if not re.search(r"\bкаждо(?:му|го|й)\b", clean, re.I):
        return 1
    m = PAYER_PAYEE_RE.search(clean)
    if not m:
        return 1
    payee = PAYEE_END_RE.split(m.group("payee"), maxsplit=1)[0]
    return max(1, len(split_parties([re.sub(r"\s+и\s+", ", ", payee)])))


def award_direction(clean: str, osi_plaintiff: bool) -> str:
    """Кто кому платит по строке «Взыскать с X в пользу Y»."""
    m = PAYER_PAYEE_RE.search(clean)
    if m:
        payer = m.group("payer")
        payee = PAYEE_END_RE.split(m.group("payee"), maxsplit=1)[0]
    else:  # «Взыскать с Иванова задолженность …» — получатель не назван
        payer, payee = clean, ""
    if OSI_RE.search(payee):
        return TO_OSI
    if OSI_RE.search(payer):
        return FROM_OSI
    if not payee and osi_plaintiff:
        return TO_OSI  # получатель не назван — значит, истец, а истец здесь ОСИ
    return OTHER


def extract_amounts(operative_lines: list[str]) -> Amounts:
    """Все суммы из строк «Взыскать ...» резолютивной части, без разделения по сторонам."""
    total = Amounts()
    for clean in _award_lines(operative_lines):
        k = _each_multiplier(clean)
        for kind, value in vars(_line_amounts(clean)).items():
            total.add(kind, value * k)
    return total


def split_amounts(operative_lines: list[str], osi_plaintiff: bool) -> dict[str, Amounts]:
    """Суммы по направлениям: в пользу ОСИ, с ОСИ, между другими участниками."""
    out = {TO_OSI: Amounts(), FROM_OSI: Amounts(), OTHER: Amounts()}
    for clean in _award_lines(operative_lines):
        target = out[award_direction(clean, osi_plaintiff)]
        k = _each_multiplier(clean)
        for kind, value in vars(_line_amounts(clean)).items():
            target.add(kind, value * k)
    return out


def classify_topic(claim: str) -> str:
    for name, rx in TOPICS:
        if rx.search(claim):
            return name
    return "Другое" if claim else ""


# --- главный разбор --------------------------------------------------------------------------

def _doc_type(lines: list[str]) -> str:
    for line in lines[:8]:
        key = _compact(line)
        if not key or len(key) > 30:
            continue
        for marker, name in (
            ("ДОПОЛНИТЕЛЬНОЕРЕШЕНИЕ", "дополнительное решение"),
            ("ЗАОЧНОЕРЕШЕНИЕ", "заочное решение"),
            ("РЕШЕНИЕ", "решение"),
            ("ОПРЕДЕЛЕНИЕ", "определение"),
            ("ПОСТАНОВЛЕНИЕ", "постановление"),
        ):
            if key.startswith(marker):
                return name
    return "не определён"


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def _court(header: list[str]) -> str:
    for i, line in enumerate(header):
        if not re.search(r"\bсуд\w*\b", line, re.I):
            continue
        joined = _norm(line + " " + (header[i + 1] if i + 1 < len(header) else ""))
        m = re.match(r"(.*?\bсуд\b.*?)\s+в\s+составе", joined, re.I)
        if m:
            return m.group(1).strip(" ,")
        m = re.match(
            r"Судья\s+(.*?\bсуда\b.*?)(?=\s+[А-ЯЁӘІҢҒҮҰҚӨҺ][а-яёәіңғүұқөһ]+\s+[А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?|,)",
            joined,
        )
        if m:
            court = m.group(1).strip(" ,")
            return court[0].upper() + court[1:]
        return ""
    return ""


def normalize_judge(name: str) -> str:
    """«А.Ж. Баймахан», «Д.К.Жусупова», «Баймахан А. Ж.» -> «Баймахан А.Ж.»."""
    name = _norm(name).strip(" ,.:")
    m = re.fullmatch(r"((?:[А-ЯЁӘІҢҒҮҰҚӨҺ]\.\s?){1,2})\s*([А-ЯЁӘІҢҒҮҰҚӨҺ][\w\-]+)", name)
    if m:
        return f"{m.group(2)} {m.group(1).replace(' ', '')}"
    m = re.fullmatch(r"([А-ЯЁӘІҢҒҮҰҚӨҺ][\w\-]+)\s+((?:[А-ЯЁӘІҢҒҮҰҚӨҺ]\.?\s?){1,2})", name)
    if m:
        initials = "".join(f"{c}." for c in re.findall(r"[А-ЯЁӘІҢҒҮҰҚӨҺ]", m.group(2)))
        return f"{m.group(1)} {initials}"
    return name


def _judge(lines: list[str], header_text: str) -> str:
    for line in reversed(lines):
        stripped = line.strip()
        if re.match(r"Судья\b", stripped) and len(stripped) < 120:
            name = _norm(re.sub(r"^Судья\s*:?", "", stripped))
            if name:
                return normalize_judge(name)
    m = re.search(r"судь[яи]\s+([А-ЯЁӘІҢҒҮҰҚӨҺ][^\s,]+\s+[А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?)", header_text)
    return normalize_judge(m.group(1)) if m else ""


def parse_decision(text: str, file: str = "") -> Decision:
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n")]
    nonempty = [l for l in lines if l.strip()]
    d = Decision(file=file, text_length=len(text))
    d.doc_type = _doc_type(nonempty)

    header, blocks = _sections(nonempty)
    header_text = _norm(" ".join(header))

    # Номер дела и дата: строка с номером обычно содержит и дату (в шапке или в таблице внизу).
    m = CASE_NO_RE.search(text)
    if m:
        d.case_number = m.group(1)
        line = next(l for l in nonempty if d.case_number in l)
        d.date = _parse_date(line)
        city = re.search(r"(?:город|г\.)\s*([А-ЯЁӘІҢҒҮҰҚӨҺ][а-яёәіңғүұқөһ\-]+)", line)
        d.city = city.group(1) if city else ""
    if d.date is None:
        d.date = _parse_date(" ".join(nonempty[:12]))

    d.court = _court(header)
    d.judge = _judge(nonempty, header_text)
    low = header_text.lower()
    if "упрощенн" in low or "упрощённ" in low:
        d.procedure = "упрощённое (письменное)"
    elif "заседани" in low:
        d.procedure = "судебное заседание"

    d.plaintiffs = split_parties(_block(blocks, "ИСТЕЦ", "ИСТЦЫ", "ЗАЯВИТЕЛ") or [])
    d.defendants = split_parties(_block(blocks, "ОТВЕТЧИК") or [])
    d.third_parties = split_parties(_block(blocks, "ТРЕТЬ") or [])
    d.claim = _norm(" ".join(_block(blocks, "ТРЕБОВАНИ") or []))

    operative: list[str] = []
    for key, block_lines in blocks:
        if key.startswith(OPERATIVE):
            operative = []
            for line in block_lines:
                stripped = line.strip()
                if re.match(r"Судья\b", stripped):
                    break
                if not BOILERPLATE_RE.match(stripped):
                    operative.append(stripped)
            break
    operative_text = _norm(" ".join(operative))
    if operative:
        d.outcome = classify_outcome(operative_text)
        d.outcome_text = _norm(operative[0])
        split = split_amounts(operative, osi_plaintiff="истец" in d.osi_role)
        d.amounts, d.osi_pays, d.other_awards = split[TO_OSI], split[FROM_OSI], split[OTHER]
        d.obligations = sum(1 for l in operative if re.match(r"(Обязать|Признать)\b", l))

    d.topic = classify_topic(d.claim or d.outcome_text)
    d.citations, unresolved = extract_citations(text)
    d.resolutions = sorted({_norm(m.group(1)) for m in RESOLUTION_RE.finditer(text)})

    if not d.case_number:
        d.warnings.append("номер дела не найден")
    if d.date is None:
        d.warnings.append("дата не найдена")
    if not d.court:
        d.warnings.append("суд не найден")
    if d.is_decision:
        if not d.plaintiffs:
            d.warnings.append("истец не найден")
        if not d.defendants:
            d.warnings.append("ответчик не найден")
        if not d.claim:
            d.warnings.append("требования истца не найдены")
        if not operative:
            d.warnings.append("резолютивная часть («РЕШИЛ:») не найдена")
        elif d.outcome == UNKNOWN:
            d.warnings.append("исход не распознан")
    d.unresolved_citations = unresolved
    if unresolved:
        d.warnings.append(f"ссылок на статьи без понятного закона: {len(unresolved)}")
    return d
