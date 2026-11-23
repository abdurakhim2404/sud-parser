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
LOWER_HEADING_RE = re.compile(
    r"(?:истц?ы?|истец|ответчик\w*|трет\w+\s+лиц\w*|требовани\w+\s+истц\w*|заявител\w*)"
    r"(?:\s+по\s+(?:первоначальному|основному|первому|встречному)\s+иску)?$", re.I)
# Упрощённое решение без блоков: «…гражданское дело по иску ОСИ "Х" к К. А. К. о возмещении ущерба».
INLINE_PARTIES_RE = re.compile(
    r"по\s+(?:исковому\s+заявлению|иску)\s+(.{3,300}?)\s+к\s+(.{2,300}?)\s+((?:о|об)\s[^,.;]{3,200})", re.I)
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
    claim_amount: float | None = None   # сумма иска (что просил истец), без судебных расходов
    special: bool = False               # особое производство: заявитель без ответчика
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


# Прочие персональные данные в полном тексте решения.
_IIN_RE = re.compile(r"(?<![\d/-])\d{12}(?![\d/-])")                     # ИИН (и БИН — их не различить)
_IBAN_RE = re.compile(r"\bKZ\d{2}[0-9A-Z]{13,16}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
# «кв. 45», «квартира №12», «45-пәтер», «пәтер 3»: номер квартиры вместе с адресом указывает на человека.
# «кв.5относится» — после номера бывает слово без пробела, поэтому без \b в конце.
_FLAT_RE = re.compile(r"\b((?:кв\.?|квартир\w*|пәтер\w*|ком\.|комнат\w*)\s*№?\s*)\d+(?:/\d+)?(?:[а-яА-Я](?![а-яА-Я]))?|"
                      r"\b\d+\s*[-–]?\s*(пәтер\w*)", re.I)
_BIRTH_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\s*(?:г\.?\s*)?(?:года?\s+)?(?:рождения|г\.\s?р\.|туған)", re.I)
# Свидетель, гражданин, представитель — люди не из шапки решения. Дальше 1–3 слова имени,
# если это не орган или сторона («представитель Истца», «представитель Акимата»).
_NOT_NAME = (r"(?!(?:Истц|Ответчик|Отдел|Управлени|Акимат|Комитет|Инспекци|Банк|Товарищ|Объединени|Департамент|"
             r"Министерств|Прокурат|Республик|Государствен|Акционерн|Компани|Учрежден|Филиал|Город|Суд|Заявител|"
             r"Третье|Третьего|Кооператив|Корпораци|Центр|Агентств|Фонд|Совет|Правлени|Суд|Коммунальн|"
             r"Общества|Ассоциаци|Палат)\w*)")
_NOT_PERSON_WORD_RE = re.compile(
    r"Астан|Алмат|Шымкент|Республик|Казахстан|Қазақстан|Частн|Ішкі|істер|Министр|Департамент|Управлени|"
    r"област|облыс|район|аудан|город|қала|Акимат|әкім", re.I)
_WITNESS_RE = re.compile(
    rf"(\b(?:свидетел\w*|гражданин\w*|гражданк\w*|гр\.|представител\w*|куәгер\w*|азамат\w*|өкіл\w*|"
    rf"нотариус\w*|ЧСИ|исполнител\w*|орындаушы\w*|председател\w*(?:\s+(?:КСК|ОСИ|ПКСК))?\s*[–-]?|"
    rf"предпринимател\w*|секретар\w*(?:\s+судебного\s+заседания)?|директор\w*|бухгалтер\w*|эксперт\w*|"
    rf"специалист\w*|руководител\w*|төраға\w*|хатшы\w*)\s+)"
    rf"({_NOT_NAME}{_NAME_WORD}(?:\s+{_NOT_NAME}{_NAME_WORD}){{0,2}})")
# Инициалы перед фамилией: «Д.Ж.Оңайбеков», «А. Жанибеков» -> «Д.Ж.О.», «А. Ж.»
# Слитно («А.Жанибеков») — любое слово; через пробел — только с окончанием фамилии, иначе «… Т. Ж. Д. Суд
# считает» превратилось бы в «Т. Ж. Д. С. считает».
_SURNAME_END = (rf"(?:[{_LOW}]*(?:ов|ев|ёв|ин|ын|ий|ая|ук|юк|бек|бай|улы|ұлы|кызы|қызы)[{_LOW}]{{0,4}}|"  # «Оразалиеваның»
                rf"[{_LOW}]*(?:енко|ько))")  # «Шевченко», «Зосько» не склоняются
_INITIALS_FIRST_RE = re.compile(
    rf"(\b[{_UP}]\.(?:[{_UP}]\.)?)({_NAME_WORD})|(\b[{_UP}]\.\s(?:[{_UP}]\.\s)?)([{_UP}]{_SURNAME_END})\b")
# «Фамилия Имя» и «Имя Фамилия» без отчества («свидетель … Кожахметова Раушан», «Мирас Айдарулы»): одно из слов
# с окончанием фамилии. Но это же и улицы («улица Сағадат Нұрмағамбетов, дом 31А») — их отсекает _mask_pair.
_PERSON_PAIR_RE = re.compile(rf"\b([{_UP}]{_SURNAME_END})\s+({_NAME_WORD})\b|\b({_NAME_WORD})\s+([{_UP}]{_SURNAME_END})\b")
_STREET_BEFORE_RE = re.compile(r"(?:ул\.|улиц\w*|просп\w*|пр\.|пр-т|мкр\.?|микрорайон\w*|переул\w*|пер\.|бульвар\w*|"
                               r"шоссе|им\.|имени|көше\w*|даңғыл\w*|ауыл\w*|село|с\.|жилого\s+дома|комплекс\w*|"
                               r"[«\"]|ОСИ|по\s+улице)\s*(?:[А-ЯЁӘІҢҒҮҰҚӨҺ][\w-]*\s+){0,2}$", re.I)
_STREET_AFTER_RE = re.compile(r"^\s*(?:,?\s*(?:дом|д\.|№|\d)|көше|даңғыл|ауыл|[»\"]|\d)", re.I)
# Фамилия перед инициалами, в том числе с опечаткой: «Суюновой Ж,М.», «Маликовой Б. А. С.»
_SURNAME_INITIALS_RE = re.compile(rf"\b([{_UP}]{_SURNAME_END})(\s+[{_UP}][.,]\s?[{_UP}][.,])")


# Слова с заглавной, которые не имена: начало предложения, роли, документы, места.
_NOT_NAME_WORD_RE = re.compile(
    r"(?:Поскольку|Между|Согласно|Однако|Также|Кроме|Таким|После|Поэтому|Вместе|Если|Когда|Учитывая|Исходя|"
    r"При|Как|Так|Это|Данн|Указанн|Собственник|Застройщик|Заказчик|Подрядчик|Исполнител|Управляющ|Копия|Копии|"
    r"Справк|Представител|Председател|Шешім|Көшірме|Үшінші|Ассоциаци|Объединени|Имуществ|Услуг|Судья|Сот|"
    r"Алмат|Астан|Қызылорд|Кызылорд|Қармақшы|Шымкент|Қазақстан|Казахстан)", re.I)
_PLACE_AFTER_RE = re.compile(r"^\s*(?:облыс|ауданы|ауылы|қаласы|района|области|город)", re.I)


def _not_a_name(word: str, after: str = "") -> bool:
    return bool(_NOT_NAME_WORD_RE.match(word) or _ADJECTIVE_END_RE.search(word) or _TERM_RE.match(word)
                or _NOT_PERSON_WORD_RE.search(word) or _PLACE_AFTER_RE.match(after))


def _mask_surname_initials(m: re.Match) -> str:
    return m.group(0) if _not_a_name(m.group(1)) else m.group(1)[0] + "." + m.group(2)


def _mask_initials_first(m: re.Match) -> str:
    initials, word = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    if _not_a_name(word, m.string[m.end():m.end() + 12]):
        return m.group(0)
    return initials + word[0] + "."


_ADJECTIVE_END_RE = re.compile(r"(?<!ов)(?<!ев)(?<!ин)(?<!ын)(?:ый|ой|ое|ые|ого|ому|ыми|ых|ий|ая|ей|ую|ими|их|кое)$")  # «Кужахметовой» — фамилия
_TERM_RE = re.compile(r"(?:Кодекс|Закон|Конституц|Постановлени|Указ|Правил|Положени|Устав|Договор|Протокол|Акт|"
                      r"Решени|Определени|Заключени|Истец|Ответчик|Жауапкер|Талапкер|Иск|Суд|Республик)", re.I)


def _mask_pair(m: re.Match) -> str:
    before = m.string[max(0, m.start() - 40):m.start()]
    after = m.string[m.end():m.end() + 12]
    if _STREET_BEFORE_RE.search(before) or _STREET_AFTER_RE.search(after):
        return m.group(0)
    first, second = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    if re.match(_NOT_NAME + r"\w", first) is None or re.match(_NOT_NAME + r"\w", second) is None:
        return m.group(0)
    # Прилагательные и термины: «Налоговый Кодекс», «Гражданский Кодекс», «Поскольку Застройщиком».
    if any(_not_a_name(w) for w in (first, second)) or _PLACE_AFTER_RE.match(after):
        return m.group(0)
    return f"{first[0]}. {second[0]}."


_ID_DOC_RE = re.compile(r"((?:удостоверени\w*\s+личности|паспорт\w*|жеке\s+куәлік\w*)\s*(?:№|N)?\s*)\d{6,}", re.I)


def mask_document(text: str, parties: list[str] = ()) -> str:
    """Полный текст решения без персональных данных — для выдачи другим программам (ботам).

    Кроме ФИО (как в mask_text) скрывает фамилию стороны-физлица, упомянутую отдельно («ответчик Петров
    пояснил»), ИИН, номера счетов, телефоны, почту, номера квартир, даты рождения и номера документов.
    Названия ОСИ, компаний и госорганов, суммы, даты и номера дел остаются."""
    text = mask_text(text, parties)
    for name in parties:
        if party_kind(name) != PERSON:
            continue
        words = re.findall(_NAME_WORD, name)[:3]
        # Сторона, которую не распознали как организацию («… Астаны», «Қазақстан Республикасы Ішкі …»):
        # её слова не прячем по всему тексту, иначе пропадут названия городов и органов.
        if not words or (len(words) < 2 and len(words[0]) < 5) or _NOT_PERSON_WORD_RE.search(name):
            continue
        # Каждое слово ФИО отдельно: фамилия без инициалов, имя впереди (казахский порядок), отчество.
        # Окончание падежа — не длиннее 3 букв: фамилия «Жилин» не должна задеть «Жилищного кодекса».
        for w in words:
            if len(w) < 3:
                continue
            pattern = rf"\b{_stem(w)}[{_LOW}]{{0,3}}\b" if len(w) > 4 else rf"\b{re.escape(w)}[{_LOW}]{{0,2}}\b"
            text = re.sub(pattern, f"{w[0]}.", text)
    text = _WITNESS_RE.sub(lambda m: m.group(1) + _initials(m.group(2)), text)
    text = _PERSON_PAIR_RE.sub(_mask_pair, text)
    text = _SURNAME_INITIALS_RE.sub(_mask_surname_initials, text)
    text = _INITIALS_FIRST_RE.sub(_mask_initials_first, text)
    text = _IIN_RE.sub("[ИИН]", text)
    text = _IBAN_RE.sub("[счёт]", text)
    text = _PHONE_RE.sub("[телефон]", text)
    text = _EMAIL_RE.sub("[почта]", text)
    text = _BIRTH_RE.sub("[дата рождения]", text)
    text = _ID_DOC_RE.sub(lambda m: m.group(1) + "[номер]", text)
    text = _FLAT_RE.sub(lambda m: (m.group(1) + "[№]") if m.group(1) else "[№] " + m.group(2), text)
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
    head = re.sub(r"\([^()]*\)", " ", head)  # «В СУДЕ УЧАСТВОВАЛИ(посредством WhatsApp):»
    letters = [c for c in head if c.isalpha()]
    if not letters:
        return None
    # Обычно заголовок прописными («ОТВЕТЧИК:»), но бывает «Ответчик:» и «ОТВЕТЧИК по первому иску:».
    if any(c.islower() for c in letters) and not (_ and LOWER_HEADING_RE.match(head.strip())):
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
        # «ТРЕБОВАНИЙ НА ПРЕДМЕТ СПОРА:» или просто «ТРЕБОВАНИЯ:» — но не «ТРЕБОВАНИЯ ИСТЦА:»
        if h and (h[0].startswith("ТРЕБОВАНИЙ") or h[0] in ("ТРЕБОВАНИЯ", "ТРЕБОВАНИЕ")) and blocks \
                and blocks[-1][0].startswith("ТРЕТЬ") and not blocks[-1][1]:
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
            part = re.sub(r"^\d{1,2}[.)]\s*", "", _norm(part).strip(" ,;.:–-"))  # «1. ТОО …»
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


# --- Сумма иска: что истец просил взыскать (без судебных расходов) ---------------------------------
# Ищем в описательной части предложения, где говорит истец: «просит взыскать…», «обратился с иском
# о взыскании…», «уточнив требования…». Рассуждения суда («подлежит взысканию») и просьбы ответчика
# пропускаем. Уточнённые требования важнее первоначальных — берём последние.
CLAIM_SAY_RE = re.compile(
    r"\bпрос(?:ит|ил[аи]?|ят|или)\b|\bтребу\w*|заявил\w*\s+требовани|обратил\w*\s+(?:в\s+суд|с\s+иск)|"
    r"предъявил\w*|исков\w*\s+требовани|"
    r"цен\w*\s+иска|сумм\w*\s+(?:иска|требований)|сұра\w*|талап\s+ет\w*|талап\s+қой\w*", re.I)
# Уточнение иска, а не «дополнительное соглашение» или «увеличение тарифа».
CLAIM_REFINED_RE = re.compile(
    r"уточн\w*|увеличи(?:в|л\w*)\b|уменьши(?:в|л\w*)\b|дополни(?:в|л\w*)\b|"
    r"(?:увеличени|уменьшени|дополнени)\w*\s+(?:исков|иска|требован|размер\w*\s+исков)|нақтыла|көбейт|азайт", re.I)
CLAIM_DIRECT_RE = re.compile(r"цен\w*\s+иска|сумм\w*\s+(?:иска|требований)\s+(?:составля|—|-)", re.I)
CLAIM_SKIP_RE = re.compile(
    r"ответчик\w*\s+(?:в\s+\w+\s+)?(?:прос|ходатайств|заяв)|представител\w*\s+ответчик|встречн|"
    r"подлеж\w*\s+взыскан|суд\s+(?:считает|полагает|приходит|находит)|взыскав\b|претензи|"
    r"отзыв|возраж|не\s+соглас|в\s+иске\s+отказать|отказать\s+в\s+(?:удовлетворении|иске)|"
    r"^\s*взыскать\b|^\s*\d+\.\s*взыскать\b", re.I)
# В иске должны просить деньги, а не только «признать решение об утверждении тарифа 50 тенге».
CLAIM_MONEY_RE = re.compile(r"взыск|возмещ|возмест|выплат|верну|возврат|компенсац|задолж|неустойк|\bпен[ияюе]\b|"
                            r"ущерб|убытк|\bдолг|өндір|қайтар|өтеу|берешек|қарыз", re.I)
# Дальше идёт разбивка уже названной суммы: «3 740 430 тенге, включающаяся в себя: 1) …».
CLAIM_BREAKDOWN_RE = re.compile(r"включа\w*|в\s+том\s+числе|из\s+(?:них|которых)|состоящ\w*\s+из|оның\s+ішінде", re.I)
# Тарифы и ставки: «50 тенге с кв.м.», «28 000 тенге в месяц».
CLAIM_RATE_RE = re.compile(r"\s*(?:с|за|на)\s+(?:1\s*)?(?:кв|м2|м²|квадрат|один)|\s*в\s+(?:месяц|год)|\s*ежемесячн", re.I)
# После «взыскать …» идут другие требования: «…, признать договор расторгнутым, признать акт на сумму …».
CLAIM_NEXT_DEMAND_RE = re.compile(r"\b(?:признать|обязать|расторгнуть|установить|отменить|выселить|освободить)\b", re.I)
# Сумма судебных расходов — не часть иска: «государственной пошлины в размере …», «услуг представителя …».
CLAIM_COST_RE = re.compile(
    r"пошлин|представит|предс?т?а?в?ит\w*\s+(?:расход|услуг)|юридическ\w*\s+(?:услуг|помощ)|почтов|курьер|"
    r"нотари|исполнительн\w*\s+надпис|составлени\w*\s+(?:иска|исков|заявлен)|"
    r"доверенност|эксперт|"
    r"оценк|издерж|судебн\w*\s+расход|баж|өкіл|сот\s+шығын", re.I)


def claim_candidates(body: str, claim_block: str = ""):
    """Предложения со словами истца и суммами: (вид, сумма, предложение); вид — refined / direct / initial."""
    def clean(t: str) -> str:
        t = _norm(t.replace("\xa0", " "))
        t = re.sub(r"\b(\d{4,})\s(\d{3})(?=\s*(?:тенге|теңге|тг\b))", r"\1\2", t)  # «5000 000 тенге»
        return re.sub(r"(\d)\s*,\s+(\d{1,2})(?=\s*(?:тенге|теңге|тг\b))", r"\1,\2", t)  # «478 627, 20 тенге»

    # Не режем на инициалах: «взыскать с К. Е. Б. 17599 тенге».
    sentences = re.split(r"(?<=[.;])(?<!\b[А-ЯЁӘІҢҒҮҰҚӨҺ]\.)\s+(?=[А-ЯЁӘІҢҒҮҰҚӨҺ\d«])", clean(body))
    if claim_block:
        sentences.insert(0, "просит " + clean(claim_block))
    for s in sentences:
        refined, direct = CLAIM_REFINED_RE.search(s), CLAIM_DIRECT_RE.search(s)
        if not MONEY_RE.search(s) or CLAIM_SKIP_RE.search(s) or not (CLAIM_SAY_RE.search(s) or refined):
            continue
        if not (direct or CLAIM_MONEY_RE.search(s)) or len(s) > 1500:
            continue  # длинный кусок без точек — обычно шапка решения, а не требование
        s = re.sub(r"«[^»]{25,}»", " ", s)  # «О взыскании … 3 720 050 тенге» — название документа, не иск
        # Деньги считаем от «взыскать» до следующего неденежного требования.
        start = re.search(r"взыск|өндір", s, re.I)
        before = CLAIM_NEXT_DEMAND_RE.search(s, 0, start.start()) if start else None
        separate = re.search(r"(?:[;,]|\bи)\s*о\s+$", s[max(0, start.start() - 8):start.start()]) if start else None
        if before and not separate and re.match(r"взыскани", s[start.start():], re.I):
            continue  # «отменить исполнительную надпись о взыскании …» — требование не денежное
        if not start and not direct and CLAIM_NEXT_DEMAND_RE.search(s):
            continue  # «признать надпись не подлежащей исполнению в сумме …» — денег не просят
        end = len(s)
        if start:
            nxt = CLAIM_NEXT_DEMAND_RE.search(s, start.end())
            end = nxt.start() if nxt else end
        brk = CLAIM_BREAKDOWN_RE.search(s, start.end() if start else 0)
        if brk and MONEY_RE.search(s, 0, brk.start()):
            end = min(end, brk.start())
        total, prev = 0.0, 0
        for m in MONEY_RE.finditer(s):
            if not direct and (start and m.start() < start.start() or m.start() >= end):
                continue
            near = s[max(prev, m.start() - 70):m.start()]
            prev = m.end()
            if CLAIM_COST_RE.search(near) or TOTAL_RE.search(near) or CLAIM_RATE_RE.match(s, m.end()):
                continue
            if re.search(r"\bпо\s*$", near) and EACH_RE.search(s[m.end():m.end() + 40]):
                continue  # «по 125 000 тенге с каждого» — разбивка уже названной суммы
            total += _parse_money(m.group(1), m.group(2))
        if total <= 0:
            continue
        kind = "direct" if direct else "refined" if refined else "initial"
        yield kind, total, s


def claim_amount(body: str, claim_block: str = "") -> float | None:
    """Сумма иска по описательной части решения; None — в тексте её нет (часто в коротких решениях)."""
    initial = refined = direct = None
    for kind, total, _ in claim_candidates(body, claim_block):
        if kind == "direct":
            direct = total
        elif kind == "refined":
            refined = total
        elif initial is None:
            initial = total
    value = refined if refined is not None else direct if direct is not None else initial
    return round(value, 2) if value is not None else None


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
    # третьи лица бывают в двух блоках: «на стороне истца» и «на стороне ответчика»
    d.third_parties = split_parties([l for key, ls in blocks if key.startswith("ТРЕТЬ") for l in ls])
    d.special = not d.defendants and _block(blocks, "ЗАЯВИТЕЛ") is not None
    if not d.plaintiffs and not d.defendants:
        m = INLINE_PARTIES_RE.search(header_text)
        if m:
            d.plaintiffs, d.defendants = split_parties([m.group(1)]), split_parties([m.group(2)])
            d.claim = d.claim or _norm(m.group(3))
    d.claim = _norm(" ".join(_block(blocks, *CLAIM_HEADINGS) or [])) or d.claim

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

    joined = "\n".join(nonempty)
    op = OPERATIVE_INLINE_RE.search(joined)
    d.claim_amount = claim_amount(joined[:op.start()] if op else "", d.claim)

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
