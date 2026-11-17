"""Папка решений -> список разобранных решений -> статистика практики."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .extract import (
    PARTIAL, REFUSED, SATISFIED, UNKNOWN, Citation, Decision, parse_decision,
)
from .reader import SUPPORTED, list_files, read_text

MAIN_OUTCOMES = (SATISFIED, PARTIAL, REFUSED)


@dataclass
class Excluded:
    file: str
    case_number: str
    reason: str


@dataclass
class PracticeResult:
    decisions: list[Decision] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    files_total: int = 0


def analyze_folder(folder: Path) -> PracticeResult:
    return analyze_folders([folder])


def analyze_folders(folders: list[Path]) -> PracticeResult:
    """Несколько папок как одна выборка. Одно и то же дело из разных папок считается один раз."""
    many = len(folders) > 1
    files = [path for folder in folders for path in list_files(folder)]
    parsed: list[Decision] = []
    errors: list[tuple[str, str]] = []
    for path in files:
        name = f"{path.parent.name}/{path.name}" if many else path.name
        if path.suffix.lower() not in SUPPORTED:
            errors.append((name, "формат не поддерживается (нужен .docx, .rtf или .txt)"))
            continue
        try:
            text = read_text(path)
        except Exception as exc:  # один битый файл не должен останавливать анализ
            errors.append((name, str(exc)))
            continue
        parsed.append(parse_decision(text, name))
    result = select_decisions(parsed)
    result.errors = errors
    result.files_total = len(files)
    return result


def select_decisions(parsed: list[Decision]) -> PracticeResult:
    """Отсеять не-решения (определения и т. п.) и дубли одного дела."""
    result = PracticeResult()
    by_case: dict[str, list[Decision]] = defaultdict(list)
    for d in parsed:
        if not d.is_decision:
            result.excluded.append(Excluded(d.file, d.case_number, f"не решение по существу ({d.doc_type})"))
            continue
        by_case[d.case_number or f"файл:{d.file}"].append(d)
    for group in by_case.values():
        group.sort(key=lambda d: d.text_length, reverse=True)  # мотивированное решение полнее краткого
        result.decisions.append(group[0])
        for dup in group[1:]:
            result.excluded.append(Excluded(
                dup.file, dup.case_number, f"второй файл того же дела; взят более полный «{group[0].file}»"))
    result.decisions.sort(key=lambda d: (d.date or date.min, d.case_number))
    return result


# --- статистика -------------------------------------------------------------------------------

def side_group(d: Decision) -> str:
    if d.osi_role == "истец":
        return f"ОСИ — истец, против: {d.opponent or 'не определено'}"
    if d.osi_role == "ответчик":
        return f"ОСИ — ответчик, истец: {d.opponent or 'не определено'}"
    if d.osi_role == "нет":
        return "ОСИ не сторона спора"
    # Например, новое ОСИ требует документы у прежнего КСК: «выиграло ли ОСИ» здесь не имеет смысла.
    return "ОСИ (КСК) с обеих сторон"


WON, PARTLY, LOST = "выиграло", "частично", "проиграло"


def osi_result(d: Decision) -> str | None:
    """Чем дело кончилось для ОСИ. None — если исход или роль ОСИ не определены.

    Иск удовлетворён частично — это «частично» для любой стороны: истец получил не всё,
    ответчик отбился не от всего. Раньше частичное удовлетворение считалось победой
    ОСИ-истца, но поражением ОСИ-ответчика; теперь правило одинаковое для обеих сторон.
    """
    if d.outcome not in MAIN_OUTCOMES or d.osi_role not in ("истец", "ответчик"):
        return None
    if d.outcome == PARTIAL:
        return PARTLY
    plaintiff_won = d.outcome == SATISFIED
    return WON if plaintiff_won == (d.osi_role == "истец") else LOST


def osi_won(d: Decision) -> bool | None:
    """Выиграло ли ОСИ хотя бы частично."""
    r = osi_result(d)
    return None if r is None else r != LOST


@dataclass
class OutcomeRow:
    label: str
    counts: Counter
    results: Counter  # WON / PARTLY / LOST для ОСИ

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def won(self) -> int:
        return self.results[WON]

    @property
    def partly(self) -> int:
        return self.results[PARTLY]

    @property
    def lost(self) -> int:
        return self.results[LOST]

    @property
    def known(self) -> int:
        return self.won + self.partly + self.lost

    @property
    def win_share(self) -> float | None:
        """Доля полных побед ОСИ среди дел, где ОСИ — сторона."""
        return self.won / self.known if self.known else None


def outcome_table(decisions: list[Decision], key) -> list[OutcomeRow]:
    groups: dict[str, list[Decision]] = defaultdict(list)
    for d in decisions:
        groups[key(d)].append(d)
    rows = []
    for label, items in groups.items():
        rows.append(OutcomeRow(
            label=label,
            counts=Counter(d.outcome for d in items),
            results=Counter(r for r in map(osi_result, items) if r),
        ))
    rows.sort(key=lambda r: (-r.total, r.label))
    return rows


@dataclass
class ArticleRow:
    citation: Citation
    decisions: int
    outcomes: Counter


def article_table(decisions: list[Decision], procedural: bool = False) -> list[ArticleRow]:
    """Сколько решений ссылается на каждую статью и чем эти дела закончились."""
    count: Counter = Counter()
    outcomes: dict[Citation, Counter] = defaultdict(Counter)
    for d in decisions:
        for c in d.citations:
            if c.procedural != procedural:
                continue
            count[c] += 1
            outcomes[c][d.outcome] += 1
    rows = [ArticleRow(c, n, outcomes[c]) for c, n in count.items()]
    rows.sort(key=lambda r: (-r.decisions, r.citation.law, _article_key(r.citation.article)))
    return rows


def _article_key(article: str) -> tuple[int, int]:
    main, _, sub = article.partition("-")
    return int(main), int(sub or 0)


@dataclass
class MoneyStats:
    decisions: int
    principal_total: float
    principal_min: float
    principal_median: float
    principal_max: float
    penalty_total: float
    state_fee_total: float
    lawyer_total: float
    other_total: float


def money_stats(decisions: list[Decision]) -> MoneyStats | None:
    # Только дела, где ОСИ — сторона: иначе в статистику ОСИ попали бы чужие взыскания.
    with_money = [d for d in decisions if d.amounts.principal > 0 and d.osi_role != "нет"]
    if not with_money:
        return None
    principals = [d.amounts.principal for d in with_money]
    return MoneyStats(
        decisions=len(with_money),
        principal_total=sum(principals),
        principal_min=min(principals),
        principal_median=statistics.median(principals),
        principal_max=max(principals),
        penalty_total=sum(d.amounts.penalty for d in with_money),
        state_fee_total=sum(d.amounts.state_fee for d in with_money),
        lawyer_total=sum(d.amounts.lawyer for d in with_money),
        other_total=sum(d.amounts.other_costs for d in with_money),
    )


@dataclass
class OsiPaysStats:
    decisions: int
    total: float
    lawyer_total: float
    state_fee_total: float


def osi_pays_stats(decisions: list[Decision]) -> OsiPaysStats | None:
    """Сколько суды взыскали с самого ОСИ (обычно судебные расходы выигравшей стороны)."""
    paying = [d for d in decisions if d.osi_pays.total > 0 and d.osi_role != "нет"]
    if not paying:
        return None
    return OsiPaysStats(
        decisions=len(paying),
        total=round(sum(d.osi_pays.total for d in paying), 2),
        lawyer_total=sum(d.osi_pays.lawyer for d in paying),
        state_fee_total=sum(d.osi_pays.state_fee for d in paying),
    )


def court_key(d: Decision) -> str:
    """Суд по коду в номере дела (первые 4 цифры): название в тексте бывает в разных падежах."""
    return d.case_number[:4] if d.case_number else d.court


def court_names(decisions: list[Decision]) -> dict[str, str]:
    names: dict[str, list[str]] = defaultdict(list)
    for d in decisions:
        if d.court:
            names[court_key(d)].append(d.court)
    result = {}
    for key, variants in names.items():
        nominative = [v for v in variants if " суд " in f" {v.lower()} "]
        result[key] = (nominative or variants)[0]
    return result


def warnings_count(decisions: list[Decision]) -> int:
    return sum(1 for d in decisions if d.warnings or d.outcome == UNKNOWN)
