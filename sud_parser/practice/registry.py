"""Выгрузка решений в формат таблицы «Реестр судебных решений ЖКХ» (лист «Решения»).

    python -m sud_parser.practice.registry --out data/registry <папка> [<папка> …]

Что получается в --out:
- registry.csv — строки реестра в порядке колонок листа (импорт CSV в Google Таблицы);
- registry.tsv — те же строки для вставки Ctrl+V в первую пустую строку листа;
- decisions/<город латиницей>/<год>/<номер дела>.<ext> — копии файлов, путь из колонки «Файл».

Правила — с листа «Инструкция»: ФИО физлиц не вносим («Физлицо»), суммы числом без пробелов,
даты ГГГГ-ММ-ДД, тип стороны и вердикт — из выпадающих списков.
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import acts
from .analyze import analyze_folders, court_key, court_names
from .reader import read_text
from .extract import (
    NO_CONSIDERATION, OSI, PARTIAL, PERSON, REFUSED, SATISFIED, TERMINATED, Decision, display_party,
    party_kind,
)

COLUMNS = [
    "ID записи", "Город / регион", "Суд", "Номер дела", "Год", "Дата решения", "Инстанция", "Тип производства",
    "ID категории", "Категория", "Истец", "Тип истца", "Ответчик", "Тип ответчика", "Третьи лица",
    "Предмет спора (требования)", "Сумма иска, тг", "Взыскано, тг", "Вердикт", "Ссылка на источник",
    "Файл (относительный путь)", "Скачал", "Дата загрузки", "Примечание",
]

VERDICTS = {SATISFIED: "Удовлетворено полностью", PARTIAL: "Удовлетворено частично", REFUSED: "Отказано",
            TERMINATED: "Прекращено", NO_CONSIDERATION: "Оставлено без рассмотрения"}

# Тип стороны — значения выпадающего списка реестра. Порядок важен: первое совпадение.
PARTY_TYPES = [
    ("КСК", re.compile(r"\bКСК\b|кооператив\w* собственник|ПКСК|\bМИБ\b", re.I)),
    ("Простое товарищество", re.compile(r"простое товарищество|\bПТ\b", re.I)),
    ("УК / управляющий", re.compile(r"управляющ\w* компани|\bУК\b|управляющий", re.I)),
    ("Нотариус", re.compile(r"нотариус", re.I)),
    ("ЧСИ / судебный исполнитель", re.compile(r"судебн\w* исполнител|\bЧСИ\b", re.I)),
    ("Прокурор", re.compile(r"прокур", re.I)),
    ("Госорган / акимат", re.compile(
        r"акимат|әкімдігі|государственн\w* (?:учреждени|орган|доход)|\b(?:ГУ|РГУ|КГУ|ГККП|ГКП)\b|министерств|"
        r"комитет|департамент|инспекци|управлени\w* (?:государствен|жилищ|строитель|архитектур|полици)|"
        r"мемлекеттік|Правительство для граждан|әкімі\b|\bаким\b|\bакима\b", re.I)),
    ("Застройщик", re.compile(r"строй|құрылыс|девелоп|застройщ|констракш|билдинг|construction|building|\bBI\b|Group",
                              re.I)),
    ("Подрядчик", re.compile(r"подряд|ремонт|монтаж", re.I)),
    ("Поставщик услуг", re.compile(
        r"энерго|электр|тепло|газ|gaz|energy|\bсу\b|водоканал|сервис|service|телеком|жарык|жылу|лифт|коммунал|сбыт",
        re.I)),
]

# Категория портала (текст в выдаче) -> ID и название категории реестра (лист «Категории»).
CATEGORY_MAP = [
    (re.compile(r"ЖИЛИЩН\w+ ПРАВООТНОШЕНИЙ\s+О взыскании платы за жилье", re.I),
     "47", "Жилищные: о взыскании платы за жилье и коммунальные услуги"),
    (re.compile(r"ЖИЛИЩН\w+ ПРАВООТНОШЕНИЙ\s+О выселении граждан из жилища без", re.I),
     "46", "Жилищные: о выселении без предоставления другого жилья"),
    (re.compile(r"ЖИЛИЩН\w+ ПРАВООТНОШЕНИЙ\s+О выселении граждан из жилища с", re.I),
     "120", "Жилищные: о выселении с предоставлением другого жилья"),
    (re.compile(r"ЖИЛИЩН\w+ ПРАВООТНОШЕНИЙ\s+О вселении", re.I), "217", "Жилищные: о вселении"),
    (re.compile(r"ЖИЛИЩН\w+ ПРАВООТНОШЕНИЙ\s+О выделении доли", re.I), "32", "Жилищные: о выделении доли из жилища"),
    (re.compile(r"ЖИЛИЩН\w+ ПРАВООТНОШЕНИЙ\s+Об обжаловании действий \(бездействий\) КСК", re.I),
     "158", "Жилищные: об обжаловании действий (бездействий) КСК (КСК ПК)"),
    (re.compile(r"оспаривании протокола общего собрания", re.I),
     "4", "Корпоративные споры: об оспаривании протокола общего собрания"),
    (re.compile(r"ОБ ОБЯЗАНИИ, ПОНУЖДЕНИИ", re.I), "87", "Об обязании, понуждении (исполнения, требования, предписания)"),
    (re.compile(r"освободить незаконно занимаемое нежилое", re.I),
     "97", "Об обязании освободить незаконно занимаемое нежилое помещение"),
    (re.compile(r"ЗАЩИТ\w+ ПРАВ ПОТРЕБИТЕЛ", re.I), "154", "Защита прав потребителей"),
    (re.compile(r"ВОЗМЕЩЕНИИ УЩЕРБА", re.I), "20", "Споры о возмещении ущерба"),
    (re.compile(r"нотариальные действия", re.I), "2588",
     "Жалобы на нотариальные действия, в т.ч. об отмене исполнительской надписи"),
    (re.compile(r"публичн\w+ договор", re.I), "231",
     "Взыскание задолженности по публичным договорам за потреблённые услуги (электро-, газо-, тепло-, водоснабжение)"),
    (re.compile(r"долев\w+ строительств", re.I), "113", "Договорные: с долевым строительством"),
    (re.compile(r"договор\w* подряда", re.I), "54", "Договорные: по договору подряда"),
    (re.compile(r"^\s*СПОРЫ, ВОЗНИКАЮЩИЕ ИЗ ЖИЛИЩНЫХ ПРАВООТНОШЕНИЙ\s*$", re.I),
     "212", "Споры, возникающие из жилищных правоотношений (родитель)"),
]

CITY_LATIN = {
    "Астана": "astana", "Алматы": "almaty", "Шымкент": "shymkent", "Караганда": "karaganda", "Актобе": "aktobe",
    "Атырау": "atyrau", "Павлодар": "pavlodar", "Костанай": "kostanay", "Усть-Каменогорск": "ust-kamenogorsk",
    "Семей": "semey", "Тараз": "taraz", "Уральск": "uralsk", "Актау": "aktau", "Кызылорда": "kyzylorda",
    "Петропавловск": "petropavlovsk", "Кокшетау": "kokshetau", "Туркестан": "turkestan", "Конаев": "konaev",
    "Талдыкорган": "taldykorgan", "Жезказган": "zhezkazgan", "Экибастуз": "ekibastuz", "Темиртау": "temirtau",
}
_TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяәғқңөұүһі",
                     ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r",
                      "s", "t", "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya", "a", "g",
                      "k", "n", "o", "u", "u", "h", "i"]))


def city_latin(city: str) -> str:
    if not city:
        return "unknown"
    if city in CITY_LATIN:
        return CITY_LATIN[city]
    return re.sub(r"[^a-z0-9-]+", "-", "".join(_TRANSLIT.get(ch, ch) for ch in city.lower())).strip("-") or "unknown"


# Одно написание для города: казахские варианты и обрезанное «Усть-» из текста решения.
CITY_FIX = {
    "Усть-": "Усть-Каменогорск", "Өскемен": "Усть-Каменогорск", "Түркістан": "Туркестан", "Қонаев": "Конаев",
    "Караганды": "Караганда", "Қарағанды": "Караганда", "Ақтөбе": "Актобе", "Ақтау": "Актау",
    "Қостанай": "Костанай", "Қызылорда": "Кызылорда", "Көкшетау": "Кокшетау", "Байқоңыр": "Байконыр",
    "Жезқазған": "Жезказган", "Талдықорған": "Талдыкорган", "Талғар": "Талгар", "Орал": "Уральск", "Петропавл": "Петропавловск",
}
OBLAST_KZ = {
    "Алматы": "Алматинская", "Жамбыл": "Жамбылская", "Түркістан": "Туркестанская", "Қарағанды": "Карагандинская",
    "Ақмола": "Акмолинская", "Павлодар": "Павлодарская", "Қостанай": "Костанайская", "Маңғыстау": "Мангистауская",
    "Атырау": "Атырауская", "Ақтөбе": "Актюбинская", "Қызылорда": "Кызылординская",
    "Батыс Қазақстан": "Западно-Казахстанская", "Шығыс Қазақстан": "Восточно-Казахстанская",
    "Солтүстік Қазақстан": "Северо-Казахстанская", "Абай": "Абай", "Жетісу": "Жетісу", "Ұлытау": "Ұлытау",
}


def place(d: Decision, court: str = "") -> str:
    """Город решения, а для районных судов без города — область из названия суда."""
    city = CITY_FIX.get(d.city, d.city)
    if city:
        return city
    court = f"{court} {d.court}"
    m = re.search(r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?(?:ской|цкой))\s+области", court)  # Восточно-Казахстанской
    if m:
        return m.group(1)[:-2] + "ая область"
    m = re.search(r"((?:Батыс |Шығыс |Солтүстік )?\w+)\s+облысы", court)
    if m:
        name = OBLAST_KZ.get(m.group(1), m.group(1))
        return f"{name} область" if name.endswith("ская") else f"область {name}"
    return ""


def safe_case(case_number: str) -> str:
    return re.sub(r"[\\/]", "_", case_number).strip()


def case_year(case_number: str, decided: date | None) -> str:
    """Учётный год дела из номера: 7142-25-00-2/18896 -> 2025 (по нему ищет портал)."""
    m = re.match(r"\d{4}-(\d{2})-", case_number)
    if m:
        return f"20{m.group(1)}"
    return str(decided.year) if decided else ""


def party_type(name: str, other_side_has_osi: bool, topic: str = "", defendant: bool = False,
               claim: str = "") -> str:
    kind = party_kind(name)
    if kind == PERSON:
        # в жилищных спорах человек почти всегда жилец или собственник квартиры
        return "Жилец / собственник"
    for label, rx in PARTY_TYPES:
        if label == "КСК" and rx.search(name):
            return label
    if kind == OSI:
        return "ОСИ"
    for label, rx in PARTY_TYPES:
        if rx.search(name):
            return label
    # Название не подсказывает роль — смотрим на суть спора.
    if defendant and other_side_has_osi:
        if topic.startswith("Взыскание задолженности") and not re.search(r"договор|упущенн", claim, re.I):
            return "Жилец / собственник"   # ТОО или ИП — собственник нежилого помещения, должник ОСИ
        if topic.startswith("Устранение строительных дефектов"):
            return "Застройщик"
    return "Прочее"


def party_name(name: str) -> str:
    return "Физлицо" if party_kind(name) == PERSON else display_party(name)


def side(names: list[str]) -> str:
    """Несколько физлиц — одно «Физлицо»; организации — по названиям."""
    out: list[str] = []
    for n in names:
        v = party_name(n).strip(" ;,").lstrip("«").strip()
        if v.count("«") < v.count("»"):
            v = "«" + v if not v.startswith("«") else v
        if v not in out:
            out.append(v)
    return "; ".join(out)


def category(portal_text: str) -> tuple[str, str]:
    text = " ".join((portal_text or "").split())
    for rx, cid, name in CATEGORY_MAP:
        if rx.search(text):
            return cid, name
    return "", ""


@dataclass
class Meta:
    portal_category: str = ""
    downloaded: str = ""
    note: str = ""


def read_manifest(folder: Path) -> dict[str, Meta]:
    path = folder / "_manifest.csv"
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out[r["case_number"]] = Meta(portal_category=r.get("category", ""),
                                         downloaded=(r.get("time") or "")[:10])
    return out


def to_row(d: Decision, meta: Meta, courts: dict[str, str], who: str, rel_file: str) -> list:
    cid, cname = category(meta.portal_category)
    osi_plaintiff = any(party_kind(p) == OSI for p in d.plaintiffs)
    osi_defendant = any(party_kind(p) == OSI for p in d.defendants)
    awarded = d.amounts.total + d.osi_pays.total + d.other_awards.total
    notes = []
    if meta.note:
        notes.append(meta.note)
    if meta.portal_category and not cid:
        notes.append("категория портала: " + " ".join(meta.portal_category.split())[:120])
    if d.counter_outcome:
        notes.append(f"встречный иск: {d.counter_outcome}")
    if d.warnings:
        notes.append("проверить: " + "; ".join(d.warnings))
    if not d.plaintiffs or (not d.defendants and not d.special):
        notes.append("проверить: стороны не распознаны в тексте решения")
    return [
        d.case_number,                                   # ID записи: номер дела уникален для решения
        place(d, courts.get(court_key(d), "")),
        courts.get(court_key(d), d.court),
        d.case_number,
        case_year(d.case_number, d.date),
        d.date.isoformat() if d.date else "",
        "Первая",
        "Гражданское",
        cid, cname,
        side(d.plaintiffs) or "не распознан",
        party_type(d.plaintiffs[0], osi_defendant, d.topic) if d.plaintiffs else "Прочее",
        side(d.defendants) or ("нет (особое производство)" if d.special else "не распознан"),
        party_type(d.defendants[0], osi_plaintiff, d.topic, defendant=True, claim=d.claim)
        if d.defendants else "Прочее",
        side(d.third_parties),
        d.masked(" ".join(d.claim.split()))[:300],
        str(round(d.claim_amount)) if d.claim_amount else "",  # пусто: в тексте решения суммы иска нет
        str(round(awarded)) if awarded else "",
        VERDICTS.get(d.outcome, "Прочее"),
        "",                                              # прямой ссылки нет: банк актов открывается только по ЭЦП
        rel_file,
        who,
        meta.downloaded,
        "; ".join(notes),
    ]


def party_types(d: Decision) -> tuple[list[str], list[str]]:
    """Тип каждой стороны (для JSON; в реестре — только первой)."""
    osi_plaintiff = any(party_kind(p) == OSI for p in d.plaintiffs)
    osi_defendant = any(party_kind(p) == OSI for p in d.defendants)
    return ([party_type(p, osi_defendant, d.topic) for p in d.plaintiffs],
            [party_type(p, osi_plaintiff, d.topic, defendant=True, claim=d.claim) for p in d.defendants])


def build(sources: list[tuple[Path, str, str]], out: Path, who: str, json_out: Path | None = None) -> int:
    """sources: (папка, категория портала по умолчанию, примечание по умолчанию).
    json_out — ещё и судебные акты в JSON для других программ (см. acts.py)."""
    folders = [s[0] for s in sources]
    result = analyze_folders(folders)
    metas: dict[str, Meta] = {}
    for folder, default_cat, default_note in sources:
        manifest = read_manifest(folder)
        metas.update({k: v for k, v in manifest.items() if k not in metas})
        metas.setdefault(f"__default__{folder}", Meta(default_cat, "", default_note))
    courts = court_names(result.decisions)
    rows = []
    records: list[dict] = []
    links = acts.read_links(out / "links.csv")
    many = len(folders) > 1
    for d in result.decisions:
        folder_name, _, file_name = d.file.rpartition("/") if many else ("", "", d.file)
        folder = next(f for f in folders if not many or f.name == folder_name)
        src = folder / file_name
        meta = metas.get(d.case_number) or metas[f"__default__{folder}"]
        if not meta.downloaded:
            meta = Meta(meta.portal_category, datetime.fromtimestamp(src.stat().st_mtime).date().isoformat(),
                        meta.note)
        rel = Path("decisions") / city_latin(place(d, courts.get(court_key(d), ""))) / case_year(d.case_number, d.date) / (
            safe_case(d.case_number) + src.suffix.lower())
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out / rel)
        row = to_row(d, meta, courts, who, rel.as_posix())
        rows.append(row)
        if json_out:
            records.append(acts.to_record(d, dict(zip(COLUMNS, row)), read_text(src), *party_types(d),
                                          link=links.get(d.case_number, "")))
    rows.sort(key=lambda r: (r[1], r[4], r[3]))
    if json_out:
        records.sort(key=lambda r: (r["region"], r["year"], r["case_number"]))
        acts.write(records, json_out)
    with (out / "registry.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    with (out / "registry.tsv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\n").writerows(rows)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="sud_parser.practice.registry", description="Решения -> формат реестра")
    p.add_argument("folders", nargs="+",
                   help="папки с решениями; «папка=категория портала» — категория для папок без _manifest.csv")
    p.add_argument("--out", default="data/registry")
    p.add_argument("--who", default="", help="кто скачал (колонка «Скачал»)")
    p.add_argument("--json", default="", help="ещё и судебные акты в JSON для ботов, например court_acts.json")
    args = p.parse_args(argv)
    sources = []
    for item in args.folders:
        folder, _, cat = item.partition("=")
        sources.append((Path(folder), cat, ""))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = build(sources, out, args.who, Path(args.json) if args.json else None)
    print(f"Строк реестра: {n} -> {out / 'registry.csv'}" + (f"; JSON -> {args.json}" if args.json else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
