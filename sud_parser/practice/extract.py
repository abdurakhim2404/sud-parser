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

from . import kz

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
# Номер дела: «7514-25-00-2/27138»; бывает и с обратной косой чертой «7514-25-00-2\4027».
CASE_NO_RE = re.compile(r"(\d{4}[-–]\d{2}[-–]\d{2}[-–][0-9A-Za-zА-Яа-я]{1,3}[/\\]\d+)")  # бывает «7527–24-00-2/15005»
DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\s*(?:года?\b|г\.)", re.I)  # «2025 года», «2025год», «2025 г.»

OSI_RE = re.compile(
    r"объединени\w*\s+собственник|\bОСИ\b|\bП?КСК\b|кооператив\w*\s+собственник|простое\s+товариществ|"
    + kz.OSI_KZ,
    re.I,
)
ORG_RE = re.compile(
    r"[«\"]|\bТОО\b|\bАО\b|\bНАО\b|\bИП\b|\bГУ\b|\bРГП\b|\bГКП\b|товариществ|обществ|учреждени|"
    r"предприяти|корпораци|компани|филиал|акимат|департамент|управлени|министерств|комитет|банк|"
    + kz.ORG_KZ,
    re.I,
)

# Заголовки блоков решения (сравниваются без пробелов: «Р Е Ш И Л» == «РЕШИЛ»).
HEADINGS = (
    "ИСТЕЦ", "ИСТЦЫ", "ОТВЕТЧИК", "ТРЕБОВАНИ", "ТРЕТЬ", "ВСУДЕУЧАСТВОВАЛ", "ОПИСАТЕЛЬН",
    "МОТИВИРОВОЧН", "РЕЗОЛЮТИВН", "РЕШИЛ", "СУДРЕШИЛ", "УСТАНОВИЛ", "ПОСТАНОВИЛ", "ОПРЕДЕЛИЛ",
    "ЗАЯВИТЕЛ", "ЗАИНТЕРЕСОВАНН", "ПРОКУРОР", "ПРЕДСТАВИТЕЛ", "ЗАЯВЛЕНН", "ИСКОВЫЕТРЕБОВАН",
)
# Блок требований истца: «ТРЕБОВАНИЯ ИСТЦА», «ЗАЯВЛЕННОЕ ТРЕБОВАНИЕ», «ИСКОВЫЕ ТРЕБОВАНИЯ».
# Не «ТРЕБОВАНИЙ НА ПРЕДМЕТ СПОРА» — это вторая строка заголовка «ТРЕТЬИ ЛИЦА, НЕ ЗАЯВЛЯЮЩИЕ …».
CLAIM_HEADINGS = ("ТРЕБОВАНИЯ", "ТРЕБОВАНИЕ", "ЗАЯВЛЕНН", "ИСКОВЫЕТРЕБОВАН")
OPERATIVE = ("РЕШИЛ", "СУДРЕШИЛ", "ПОСТАНОВИЛ", "ОПРЕДЕЛИЛ")
OPERATIVE_INLINE_RE = re.compile(r"(?<![А-ЯЁ])Р\s?Е\s?Ш\s?И\s?Л\s*:|" + kz.OPERATIVE_INLINE_KZ)
COUNTER_RE = re.compile(r"встречн|" + kz.COUNTER_KZ, re.I)

# Строки резолютивной части, которые разъясняют порядок обжалования, а не решают спор.
BOILERPLATE_RE = re.compile(
    r"^(на решение|на определение|ответчики? вправе|заявление подается|апелляционн|"
    r"решение (суда )?может быть обжаловано|решение суда может|решение может быть обжаловано|"
    + kz.BOILERPLATE_KZ + ")",
    re.I,
)

# Порядок важен: срабатывает первое подходящее правило. Список тем составлен по 97 решениям
# (см. PRACTICE.md) и не утверждён юристом — правится здесь и в kz.TOPICS_KZ.
TOPICS = (
    # Первым: в трудовом иске есть «задолженность по заработной плате», это не долг по взносам.
    ("Трудовые споры", re.compile(r"трудов|заработн|увольнени|восстановлени\w* на работе", re.I)),
    # Долги ОСИ взыскивает и через нотариуса; должник оспаривает надпись в суде (7 из 147 решений сбора).
    ("Исполнительная надпись нотариуса", re.compile(r"(?:исполнительн|нотариальн)\w*\s+надпис", re.I)),
    ("Принудительная ликвидация ОСИ", re.compile(r"ликвидац", re.I)),
    ("Освобождение имущества от ареста", re.compile(r"\bареста?\b|\bарестов\b", re.I)),
    # Протокол или собрание И слово об оспаривании: «передать… копии протоколов» — это спор о документах.
    ("Оспаривание решений собраний (протоколов)", re.compile(
        r"^(?=.*(?:протокол|собрани))(?=.*(?:недействительн|незаконн|отмен|юридическ\w* сил|оспарива))", re.I | re.S)),
    ("Устранение строительных дефектов", re.compile(r"дефект|недостат|устранить нарушени|гаранти", re.I)),
    # «Признать бездействие незаконным и истребовать документацию» — спор о документах, поэтому раньше
    # «оспаривания». Но только с глаголом «передать/предоставить…»: «внести изменения в документацию» — не то.
    ("Передача и предоставление документов, информации", re.compile(
        r"(?:переда|предостав|представ|истребова|верну|возврат|выда)\w*\s+(?:\S+\s+){0,6}?"
        r"(?:документ|сведени|информаци|отч[её]т|копи)|акт\w* сверки", re.I)),
    # Раньше «долгов»: «признать незаконным начисление задолженности» — оспаривание, а не взыскание.
    ("Оспаривание действий и актов (ОСИ, застройщика, госорганов)",
     re.compile(r"недействительн|незаконн|оспарива|юридической силы", re.I)),
    ("Взыскание задолженности по взносам и расходам на содержание",
     re.compile(r"задолженн|\bдолга?\b|расход\w* на содержание|взнос|неустойк", re.I)),
    ("Возмещение ущерба (затопление и т. п.)", re.compile(r"ущерб|убытк|затоплен|залив|протечк|вред", re.I)),
    ("Общее имущество, паркинг", re.compile(r"паркинг|общ\w+ имуществ", re.I)),
    ("Договорные споры", re.compile(r"договор", re.I)),
    ("Передача и предоставление документов, информации",
     re.compile(r"документ|сведени|информаци|отч[её]т", re.I)),
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
    outcome: str = UNKNOWN          # исход основного иска
    counter_outcome: str = ""       # исход встречного иска, если он был
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

    def masked(self, text: str) -> str:
        """Текст решения для отчёта: ФИО людей заменены инициалами."""
        return mask_text(text, self.plaintiffs + self.defendants + self.third_parties)

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
    if party_kind(name) == PERSON:
        return f"{PERSON} {mask_person(name)}"
    # В названии ИП и в «… в лице руководителя …» тоже бывают ФИО.
    name = _REPRESENTED_RE.sub(lambda m: m.group(1) + _initials(m.group(2).title()), name)
    return mask_text(name)


_UP, _LOW = "А-ЯЁӘІҢҒҮҰҚӨҺ", "а-яёәіңғүұқөһ"
_NAME_WORD = rf"[{_UP}][{_LOW}]+(?:-[{_UP}]?[{_LOW}]+)?"
# «Бондарева Артура Александровича», «Ахметов Серик Болатұлы»: третье слово — отчество в любом падеже.
# «Қарулы Күштері» (вооружённые силы) — не отчество, хотя оканчивается на «-улы».
_PATRONYMIC = rf"(?!Қарулы\b)[{_UP}][{_LOW}]*(?:вич|вн|ұлы|қызы|улы|кызы)[{_LOW}]*"
# Казахский порядок: «Светлана Олеговна Уразованың» — имя, отчество, фамилия.
_FULL_NAME_RE = re.compile(
    rf"\b{_NAME_WORD}\s+{_NAME_WORD}\s+{_PATRONYMIC}|\b{_NAME_WORD}\s+{_PATRONYMIC}\s+{_NAME_WORD}")
# «Кудабаева Ж.А.», «Ким И. Р.»
_SHORT_NAME_RE = re.compile(rf"\b(?!Компани\b){_NAME_WORD}\s+[{_UP}]\.\s?(?:[{_UP}]\.)?")  # «… Компани Н.В.» — фирма
# Заглавными: «СЕЙТЕНОВ ЕРЛАН НАСУРЛАНОВИЧ»
_CAPS_NAME_RE = re.compile(rf"\b[{_UP}]{{2,}}\s+[{_UP}]{{2,}}\s+[{_UP}]{{2,}}(?:ВИЧ|ВН[АЫЕУ]|ҰЛЫ|ҚЫЗЫ|УЛЫ|КЫЗЫ)\w*")
# «ИП «Х» в лице руководителя …», «ТОО «Х» представитель …» — дальше до конца идёт ФИО человека.
_REPRESENTED_RE = re.compile(
    r"(\b(?:в\s+лице|представител[ья])\s+(?:руководителя\s+|директора\s+)?|тұлғасында\s+)(.+)$", re.I)
# То же внутри текста: «… «Ақылды мектеп» тұлғасында Пидахмет Айдын …» — дальше 2–3 слова имени.
_REPRESENTED_IN_TEXT_RE = re.compile(
    rf"(\b(?:в\s+лице|тұлғасында)\s+(?:руководителя\s+|директора\s+)?)({_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}})")


def _initials(text: str) -> str:
    return " ".join(f"{w[0]}." for w in re.findall(rf"[{_UP}][{_LOW}]*", text)[:3])


def _stem(word: str) -> str:
    return re.escape(word[:-2] if len(word) > 4 else word[:-1] if len(word) > 3 else word)


def mask_text(text: str, parties: list[str] = ()) -> str:
    """Скрыть ФИО людей в куске текста решения (резолютивная часть, требования): остаются инициалы.

    Сначала — стороны дела в любом падеже («Иск Бондарева Артура Александровича»), потом любые
    «Фамилия Имя Отчество» и «Фамилия И.О.» (представители, третьи лица). Названия ОСИ и компаний
    не трогаем: в них нет отчества."""
    # Скрытое имя сразу заменяем меткой, чтобы следующие правила не приняли «Иск Б. А.» за «Фамилия И. О.».
    hidden: list[str] = []

    def hide(initials: str) -> str:
        hidden.append(initials)
        return f"\x00{len(hidden) - 1}\x00"

    for name in parties:
        if party_kind(name) != PERSON:
            continue
        words = re.findall(_NAME_WORD, name)[:3]
        if len(words) < 2:
            continue
        initials = _initials(" ".join(words))
        full = r"\b" + r"\s+".join(_stem(w) + rf"[{_LOW}]*" for w in words)
        short = rf"\b{_stem(words[0])}[{_LOW}]*\s+{words[1][0]}\.(?:\s?{words[2][0]}\.)?" if len(words) > 2 \
            else rf"\b{_stem(words[0])}[{_LOW}]*\s+{words[1][0]}\."
        text = re.sub(full, lambda m: hide(initials), text)
        text = re.sub(short, lambda m: hide(initials), text)
    text = _REPRESENTED_IN_TEXT_RE.sub(lambda m: m.group(1) + hide(_initials(m.group(2))), text)
    text = _CAPS_NAME_RE.sub(lambda m: hide(_initials(m.group(0).title())), text)
    text = _FULL_NAME_RE.sub(lambda m: hide(_initials(m.group(0))), text)
    text = _SHORT_NAME_RE.sub(lambda m: hide(_initials(m.group(0))), text)
    # «… Уразованың.» -> «С. О. У.», а не «С. О. У..»
    text = re.sub(r"\x00(\d+)\x00\.?", lambda m: hidden[int(m.group(1))], text)
    return text


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
    kz_key = kz.heading_key(key)  # «ТАЛАП ҚОЮШЫ:» -> «ИСТЕЦ» и т. д.
    if kz_key:
        return kz_key, rest.strip()
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
        if h and h[0].startswith("ТРЕБОВАНИЙ") and blocks and blocks[-1][0].startswith("ТРЕТЬ") \
                and not blocks[-1][1]:
            # «ТРЕТЬИ ЛИЦА, НЕ ЗАЯВЛЯЮЩИЕ САМОСТОЯТЕЛЬНЫХ» / «ТРЕБОВАНИЙ НА ПРЕДМЕТ СПОРА:» —
            # один заголовок на двух строках.
            if h[1]:
                blocks[-1][1].append(h[1])
        elif h:
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


def _nearest_code_before(text: str, pos: int, reach: int = 700) -> str | None:
    """Последний кодекс, явно названный в пределах `reach` символов перед позицией."""
    chunk = text[max(0, pos - reach):pos]
    best, best_at = None, -1
    for name, rx in CODES:
        for cm in rx.finditer(chunk):
            if cm.start() > best_at:
                best, best_at = name, cm.start()
    return best


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
        if law is None and re.match(r"настоящ\w+\s+[Кк]одекс", window):
            # «…указанных в статье 7 настоящего Кодекса» — это цитата из кодекса, названного
            # чуть раньше: «Согласно статье 271 Гражданского кодекса … статье 7 настоящего Кодекса».
            law = _nearest_code_before(text, m.start())
        if law is None:
            unresolved.append(_norm(text[m.start(): m.end() + 60]))
            continue
        for article in _expand_articles(m.group(1)):
            found[Citation(law, article)] = None
    # Казахский текст: «АПК-нің 223-226-баптарын», «Заңның 42-1-бабы».
    kz_found, kz_unresolved = kz.extract_citations_kz(text, _expand_articles)
    for law, article in kz_found:
        found[Citation(law, article)] = None
    return list(found), unresolved + kz_unresolved


# --- исход и суммы ---------------------------------------------------------------------------

def classify_outcome(operative: str) -> str:
    # «удовлеторить» — опечатка, встречается в решениях. Казахские формулировки переводятся в русские.
    op = kz.outcome_to_russian(operative.lower())
    op = re.sub(r"\bудовлет\w{0,2}рить\b", "удовлетворить", op)
    partial = re.search(r"удовлетворить\s+частично|частично\s+удовлетворить", op)
    satisfy = re.search(r"\bудовлетворить\b", op)
    # «Иск … оставить без удовлетворения» — тоже отказ (так пишут в части решений).
    no = r"(?:\bотказать\b|оставить\s+без\s+удовлетворения)"
    rest_refused = re.search(rf"остальной\s+части[^.]*?{no}|{no}[^.]*?остальной\s+части", op)
    refused = re.search(no, op)
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
    r"\s*(?:тенге|теңге|тг\b|(?<=\s)(?=\d{1,2}\s*тиын))",
    re.I,
)
MONEY_KINDS = (
    ("state_fee", re.compile(r"пошлин|" + kz.MONEY_KINDS_KZ["state_fee"], re.I)),
    ("lawyer", re.compile(r"представител|юридическ\w* (?:услуг|помощ)|" + kz.MONEY_KINDS_KZ["lawyer"], re.I)),
    ("penalty", re.compile(r"неустойк|\bпен[еиьяю]|" + kz.MONEY_KINDS_KZ["penalty"], re.I)),
    ("other_costs", re.compile(r"почт|нотариал|эксперт|издерж|транспортн|курьер|услуг\w* банка|комисси|"
                               + kz.MONEY_KINDS_KZ["other_costs"], re.I)),
)
PRINCIPAL_RE = re.compile(r"задолж|долг|накоплен|взнос|капитальн|" + kz.PRINCIPAL_KZ, re.I)
COSTS_RE = re.compile(r"расход|оплат|" + kz.COSTS_KZ, re.I)


def _kind_or_none(context: str) -> str | None:
    return next((k for k, rx in MONEY_KINDS if rx.search(context)), None)


def _money_kind(context: str, after: str = "") -> str:
    """Вид суммы по словам перед ней; в казахском тексте вид часто стоит после суммы:
    «333 333 теңге өкілдің қызметі үшін» — поэтому смотрим и на `after`."""
    kind = _kind_or_none(context) or (_kind_or_none(after) if after else None)
    if kind:
        return kind
    both = context + " " + after
    # «расходы по оплате 2594 тенге» без уточнения — это судебные расходы, а не долг.
    if COSTS_RE.search(both) and not PRINCIPAL_RE.search(both):
        return "other_costs"
    return "principal"


# «…, всего 20 600 тенге» — это сумма уже перечисленного, второй раз её не считаем.
TOTAL_RE = re.compile(r"\b(?:всего|итого|в\s+общей\s+сумме|на\s+общую\s+сумму|" + kz.TOTAL_KZ + r")\b", re.I)
AWARD_RE = re.compile(r"\bвзыскать\b|" + kz.AWARD_KZ, re.I)
# Без \b перед «в»: в решениях бывает «…Ивановныв пользу» — пробел пропущен.
PAYER_PAYEE_RE = re.compile(r"\bвзыскать\b(?P<payer>.*?)в\s+пользу\b(?P<payee>.*)", re.I)
# Где кончается название получателя и начинается «за что»: «… в пользу ОСИ «Х» задолженность …».
PAYEE_END_RE = re.compile(
    r"\s(?:сумм|задолж|расход|судебн|государствен|госпошлин|оплат|возврат|нотариал|почтов|неустойк|"
    r"пен[яиюе]\b|услуг|представител|уплаченн|\d)", re.I)

TO_OSI, FROM_OSI, OTHER = "в пользу ОСИ", "с ОСИ", "между другими участниками"


def _award_lines(operative_lines: list[str]):
    """Строки «Взыскать …» («… өндірілсін») без сумм прописью в скобках."""
    for line in operative_lines:
        if not AWARD_RE.search(line):
            continue
        # «госпошлины в размере 390 175 (триста девяносто тысяч …).» — суммы с прописью, но без «тенге»:
        # число с прописью в скобках в строке «Взыскать» — это деньги.
        clean = re.sub(r"(\d)\s*\([^()\d]{4,}\)(?!\s*(?:тенге|теңге|тг\b|тиын|\d{1,2}\s*тиын))", r"\1 тенге ",
                       line, flags=re.I)
        while re.search(r"\([^()]*\)", clean):
            clean = re.sub(r"\([^()]*\)", " ", clean)
        yield _norm(clean)


EACH_RE = re.compile(r"\bкаждо(?:му|го|й)\b", re.I)
PAYER_EACH_RE = re.compile(r"\bс\s+каждого\b", re.I)


def _line_amounts(clean: str) -> tuple[Amounts, bool]:
    """Суммы строки и признак «после общей суммы идёт разбивка по 125 000 с каждого».

    «… 500 000 тенге, по 125 000 тенге с каждого» — 125 000 уже входит в 500 000, второй раз не считаем.
    """
    amounts = Amounts()
    seen_plain = False   # была сумма без «по»: это общая сумма
    breakdown = False
    for fragment in re.split(r";|,\s+(?=[^\d\s])", clean):
        prev_end = 0
        matches = list(MONEY_RE.finditer(fragment))
        for n, m in enumerate(matches):
            context = fragment[prev_end:m.start()]
            prev_end = m.end()
            after = fragment[m.end():matches[n + 1].start() if n + 1 < len(matches) else len(fragment)]
            if TOTAL_RE.search(context):
                continue
            per_person = re.search(r"\bпо\s*$", context, re.I) and EACH_RE.search(fragment[m.end():m.end() + 40])
            if per_person and seen_plain:
                breakdown = True
                continue
            if not per_person:
                seen_plain = True
            value = _parse_money(m.group(1), m.group(2))
            # «671 874 тенге 18 тиын» — тиыны после слова «тенге»
            tiyn = re.match(r"\s*(\d{1,2})\s*тиын", fragment[m.end():], re.I)
            if tiyn and not m.group(2) and re.search(r"тенге|теңге|тг", m.group(0), re.I):
                value = round(value + int(tiyn.group(1)) / 100, 2)
            kazakh = re.search(kz.AWARD_KZ, clean, re.I)
            amounts.add(_money_kind(context, after if kazakh else ""), value)
    return amounts, breakdown


def _parties_count(segment: str) -> int:
    return max(1, len(split_parties([re.sub(r"\s+и\s+", ", ", segment)])))


def _each_multiplier(clean: str) -> int:
    """«по 3 692 тенге каждому» — на каждого получателя; «по 125 000 с каждого» — с каждого плательщика."""
    kz_parts = kz.split_payer_payee(clean)
    if kz_parts and re.search(kz.PAYER_EACH_KZ, clean, re.I):
        # «А-дан, Б-дан, В-дан әр қайсысынан … 333 333 теңге … өндірілсін» — с каждого
        payer = re.sub(kz.PAYER_EACH_KZ, "", kz_parts[0], flags=re.I)
        return _parties_count(re.sub(kz.ROLE_WORDS_KZ, "", payer, flags=re.I))
    if kz_parts and re.search(kz.PAYEE_EACH_KZ, clean, re.I):
        return _parties_count(re.sub(kz.ROLE_WORDS_KZ, "", kz_parts[1], flags=re.I))
    if not EACH_RE.search(clean):
        return 1
    m = PAYER_PAYEE_RE.search(clean)
    if not m:
        return 1
    if PAYER_EACH_RE.search(clean):
        payer = re.sub(r"^\s*(?:в\s+\w+\s+порядке\s+)?с\s+", "", m.group("payer"), flags=re.I)
        return _parties_count(payer)
    return _parties_count(PAYEE_END_RE.split(m.group("payee"), maxsplit=1)[0])


def award_direction(clean: str, osi_plaintiff: bool) -> str:
    """Кто кому платит по строке «Взыскать с X в пользу Y»."""
    m = PAYER_PAYEE_RE.search(clean)
    kz_parts = None if m else kz.split_payer_payee(clean)
    if m:
        payer = m.group("payer")
        payee = PAYEE_END_RE.split(m.group("payee"), maxsplit=1)[0]
    elif kz_parts:  # «Жауапкерден талап қоюшының пайдасына … өндірілсін»
        payer, payee = kz_parts
    else:  # «Взыскать с Иванова задолженность …» — получатель не назван
        payer, payee = clean, ""
    if OSI_RE.search(payee) and OSI_RE.search(payer):
        return OTHER  # ОСИ и КСК (или союз кооперативов) с обеих сторон: чьё это «ОСИ» — неясно
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
        line, breakdown = _line_amounts(clean)
        k = 1 if breakdown else _each_multiplier(clean)
        for kind, value in vars(line).items():
            total.add(kind, value * k)
    return total


def _osi_share(clean: str) -> float:
    """Доля ОСИ, если деньги взысканы с нескольких плательщиков «в долевом порядке, в равных долях».

    При солидарном взыскании (и когда доли не названы) каждый отвечает за всю сумму — доля 1.
    """
    if not re.search(r"долев|равных\s+дол|үлестік|тең\s+үлес", clean, re.I):
        return 1.0
    m = PAYER_PAYEE_RE.search(clean)
    if m:
        payer = re.sub(r"^\s*(?:в\s+\w+\s+порядке\s+)?с\s+", "", m.group("payer"), flags=re.I)
    else:
        kz_parts = kz.split_payer_payee(clean)
        if not kz_parts:
            return 1.0
        payer = re.sub(kz.ROLE_WORDS_KZ, "", kz_parts[0], flags=re.I)
    payers = split_parties([re.sub(r"\s+и\s+", ", ", payer)])
    return 1.0 / len(payers) if len(payers) > 1 else 1.0


def split_amounts(operative_lines: list[str], osi_plaintiff: bool) -> dict[str, Amounts]:
    """Суммы по направлениям: в пользу ОСИ, с ОСИ, между другими участниками."""
    out = {TO_OSI: Amounts(), FROM_OSI: Amounts(), OTHER: Amounts()}
    for clean in _award_lines(operative_lines):
        direction = award_direction(clean, osi_plaintiff)
        line, breakdown = _line_amounts(clean)
        k = 1 if breakdown else _each_multiplier(clean)
        share = _osi_share(clean) if direction == FROM_OSI else 1.0
        for kind, value in vars(line).items():
            value *= k
            out[direction].add(kind, round(value * share, 2))
            if share < 1:  # остальное платят другие ответчики
                out[OTHER].add(kind, round(value * (1 - share), 2))
    return out


def classify_topic(claim: str) -> str:
    for name, rx in TOPICS:
        if rx.search(claim) or (name in kz.TOPICS_KZ and re.search(kz.TOPICS_KZ[name], claim, re.I)):
            return name
    return "Другое" if claim else ""


# --- главный разбор --------------------------------------------------------------------------

def _doc_type(lines: list[str]) -> str:
    for line in lines[:8]:
        key = _compact(line)
        for prefix in kz.TITLE_PREFIXES:  # «ҚАЗАҚСТАН РЕСПУБЛИКАСЫНЫҢ АТЫНАН ШЕШІМ» одной строкой
            if key.startswith(prefix) and len(key) > len(prefix):
                key = key[len(prefix):]
        if not key or len(key) > 30:
            continue
        for marker, name in (
            ("ДОПОЛНИТЕЛЬНОЕРЕШЕНИЕ", "дополнительное решение"),
            ("ЗАОЧНОЕРЕШЕНИЕ", "заочное решение"),
            ("РЕШЕНИЕ", "решение"),
            ("ОПРЕДЕЛЕНИЕ", "определение"),
            ("ПОСТАНОВЛЕНИЕ", "постановление"),
            *kz.DOC_TYPES_KZ,
        ):
            if key.startswith(marker):
                return name
    return "не определён"


# Латинские буквы, похожие на русские: «19 cентября» (латинская «c») встречается в решениях.
_LATIN_LOOKALIKES = str.maketrans("aceopxyACEOPXHKMBT", "асеорхуАСЕОРХНКМВТ")


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text.translate(_LATIN_LOOKALIKES))
    try:
        if m:
            return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        m = kz.DATE_KZ_RE.search(text)  # «2025 жылғы 6 қараша»
        if m:
            return date(int(m.group(1)), kz.MONTHS_KZ[m.group(3).lower()], int(m.group(2)))
    except ValueError:
        return None
    return None


def _court(header: list[str]) -> str:
    for line in header:  # «Қызылорда қалалық сотының құрамында:»
        m = kz.COURT_KZ_RE.match(line)
        if m and re.search(r"\bсот(?:ы|ының|тың)?\s*(?:құрамында|судьясы|$|,|:)", line, re.I) \
                and not re.match(r"\s*(?:сот\s+отырыс|төрағалық)", line, re.I):
            court = _norm(m.group(1))
            return re.sub(r"\bсот(?:ының|тың)$", "соты", court)
    for i, line in enumerate(header):
        if not re.search(r"\bсуд\w*\b", line, re.I):
            continue
        joined = _norm(line + " " + (header[i + 1] if i + 1 < len(header) else ""))
        m = re.match(r"(.*?\bсуд\b.*?)\s+в\s+составе", joined, re.I)
        if m:
            return m.group(1).strip(" ,")
        # «Судья … суда» бывает и в середине строки: «26 августа 2025 года дело № … город Астана Судья …»
        m = re.search(
            r"(?:^|\s)Судья\s+(.*?\bсуда\b.*?)(?=\s+[А-ЯЁӘІҢҒҮҰҚӨҺ][а-яёәіңғүұқөһ]+\s+[А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?|,)",
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
    text = kz.fix_latin_i(text)  # «Кодекстiң» с латинской «i» -> «Кодекстің»
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n")]
    nonempty = []
    for l in lines:
        if not l.strip():
            continue
        # «Руководствуясь статьями 223-226 ГПК, суд РЕШИЛ: Иск … удовлетворить» — заголовок посреди строки.
        op = OPERATIVE_INLINE_RE.search(l)
        if op and op.start() > 0 and l[:op.start()].strip():
            nonempty.append(l[:op.start()])
            nonempty.append(l[op.start():])
        else:
            nonempty.append(l)
    d = Decision(file=file, text_length=len(text))
    d.doc_type = _doc_type(nonempty)

    header, blocks = _sections(nonempty)
    header_text = _norm(" ".join(header))

    # Номер дела и дата: строка с номером обычно содержит и дату (в шапке или в таблице внизу).
    m = CASE_NO_RE.search(text) or kz.OLD_CASE_NO_RE.search(text)  # старый формат: «Іс №2-4397/24»
    if m:
        line = next(l for l in nonempty if m.group(1) in l)
        d.case_number = m.group(1).replace("\\", "/").replace("–", "-")
        d.date = _parse_date(line)
        city = re.search(r"(?:город|г\.)\s*([А-ЯЁӘІҢҒҮҰҚӨҺ][а-яёәіңғүұқөһ\-]+)", line) \
            or kz.CITY_KZ_RE.search(line)  # «Қызылорда қаласы»
        d.city = city.group(1) if city else ""
    if d.date is None:
        d.date = _parse_date(" ".join(nonempty[:12]))

    d.court = _court(header)
    d.judge = _judge(nonempty, header_text)
    low = header_text.lower()
    if "упрощенн" in low or "упрощённ" in low or re.search(kz.SIMPLIFIED_KZ, low):
        d.procedure = "упрощённое (письменное)"
    elif "заседани" in low or re.search(kz.HEARING_KZ, low):
        d.procedure = "судебное заседание"

    d.plaintiffs = split_parties(_block(blocks, "ИСТЕЦ", "ИСТЦЫ", "ЗАЯВИТЕЛ") or [])
    d.defendants = split_parties(_block(blocks, "ОТВЕТЧИК") or [])
    d.third_parties = split_parties(_block(blocks, "ТРЕТЬ") or [])
    d.claim = _norm(" ".join(_block(blocks, *CLAIM_HEADINGS) or []))

    operative: list[str] = []
    for key, block_lines in blocks:
        if key.startswith(OPERATIVE):
            operative = []
            for line in block_lines:
                stripped = line.strip()
                if re.match(r"(?:Председательствующий\s+)?[Сс]удья\b", stripped):
                    break
                if not BOILERPLATE_RE.match(stripped):
                    operative.append(stripped)
            break
    # Встречный иск решается в той же резолютивной части. Исход дела — это исход основного иска,
    # исход встречного храним отдельно: «В иске ОСИ отказать. Встречный иск ТОО удовлетворить» —
    # для ОСИ это проигрыш, хотя слово «удовлетворить» в тексте есть.
    main_ops = [l for l in operative if not COUNTER_RE.search(l)]
    counter_ops = [l for l in operative if COUNTER_RE.search(l)]
    if operative:
        d.outcome = classify_outcome(_norm(" ".join(main_ops)))
        if counter_ops:
            d.counter_outcome = classify_outcome(_norm(" ".join(counter_ops)))
        d.outcome_text = _norm(operative[0])
        split = split_amounts(operative, osi_plaintiff="истец" in d.osi_role)
        d.amounts, d.osi_pays, d.other_awards = split[TO_OSI], split[FROM_OSI], split[OTHER]
        d.obligations = sum(1 for l in operative if re.match(r"(Обязать|Признать)\b", l))

    d.topic = classify_topic(d.claim or d.outcome_text)
    d.citations, unresolved = extract_citations(text)
    d.resolutions = sorted({_norm(m.group(1)) for rx in (RESOLUTION_RE, kz.RESOLUTION_KZ_RE)
                            for m in rx.finditer(text)})

    if not d.case_number:
        d.warnings.append("номер дела не найден")
    if d.date is None:
        d.warnings.append("дата не найдена")
    if not d.court:
        d.warnings.append("суд не найден")
    if d.is_decision:
        if not d.plaintiffs:
            d.warnings.append("истец не найден")
        if not d.defendants and not _block(blocks, "ЗАЯВИТЕЛ"):  # в особом производстве ответчика нет
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
