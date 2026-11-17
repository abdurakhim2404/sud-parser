"""Excel-отчёт по судебной практике."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .analyze import (
    MAIN_OUTCOMES, PracticeResult, article_table, court_key, court_names, money_stats,
    osi_pays_stats, outcome_table, side_group,
)
from .extract import display_party

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
TITLE_FONT = Font(bold=True, size=12)
SMALL_SAMPLE = 30  # меньше — проценты показываем, но с предупреждением

OUTCOME_HEADER = ["Удовлетворён", "Частично", "Отказано", "Прочее", "Всего",
                  "ОСИ выиграло", "ОСИ частично", "ОСИ проиграло"]


RULE_NOTE = ("«ОСИ выиграло»: ОСИ-истцу иск удовлетворён полностью или ОСИ-ответчику в иске отказано. "
             "«Частично»: иск удовлетворён частично, кто бы ни был истцом. Проценты — от дел, где ОСИ сторона спора.")


def _pct(part: int, whole: int) -> str:
    return f"{part} из {whole} ({part / whole:.0%})" if whole else "—"


def outcome_rows(rows) -> list[list]:
    out = []
    for r in rows:
        other = r.total - sum(r.counts[o] for o in MAIN_OUTCOMES)
        out.append([r.label, *(r.counts[o] for o in MAIN_OUTCOMES), other, r.total,
                    _pct(r.won, r.known), _pct(r.partly, r.known), _pct(r.lost, r.known)])
    return out


class _Writer:
    def __init__(self, ws):
        self.ws = ws
        self.widths: dict[int, int] = {}

    def title(self, text: str) -> None:
        if self.ws.max_row > 1:
            self.ws.append([])
        self.ws.append([text])
        self.ws.cell(self.ws.max_row, 1).font = TITLE_FONT

    def note(self, text: str) -> None:
        self.ws.append([text])
        self.ws.cell(self.ws.max_row, 1).font = Font(italic=True, color="666666")

    def table(self, header: list[str], rows: list[list]) -> None:
        self.ws.append(header)
        for cell in self.ws[self.ws.max_row]:
            cell.font = Font(bold=True)
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for r in rows:
            self.ws.append(r)
            for cell in self.ws[self.ws.max_row]:
                if isinstance(cell.value, float):
                    cell.number_format = "#,##0.00"
                elif hasattr(cell.value, "strftime"):
                    cell.number_format = "DD.MM.YYYY"
        for i, col in enumerate(header, start=1):
            longest = max([len(str(col))] + [len(str(r[i - 1] if r[i - 1] is not None else "")) for r in rows])
            self.widths[i] = max(self.widths.get(i, 0), min(longest + 2, 70))

    def finish(self) -> None:
        for i, w in self.widths.items():
            self.ws.column_dimensions[get_column_letter(i)].width = w


def _table_sheet(wb: Workbook, title: str, header: list[str], rows: list[list]) -> None:
    ws = wb.create_sheet(title)
    w = _Writer(ws)
    w.table(header, rows)
    w.finish()
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions


def write_practice_report(result: PracticeResult, out_dir: str | Path = "reports",
                          source: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"practice_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsx"
    decisions = result.decisions
    n = len(decisions)

    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка"
    w = _Writer(ws)

    w.title("Анализ судебной практики")
    w.table(["Показатель", "Значение"], [
        ["Папка с решениями", source],
        ["Файлов в папке", result.files_total],
        ["Решений в анализе (уникальные дела)", n],
        ["Исключено: не решения и дубли", len(result.excluded)],
        ["Не удалось прочитать", len(result.errors)],
        ["Решений с предупреждениями (проверить вручную)", sum(1 for d in decisions if d.warnings)],
        ["Период решений", _period(decisions)],
    ])
    if n < SMALL_SAMPLE:
        w.note(f"Внимание: решений меньше {SMALL_SAMPLE}. Проценты показывают только эту выборку, "
               "а не всю практику судов.")
    w.note("Выборка зависит от того, какие решения скачаны. Если специально подбирались разные исходы, "
           "доли исходов не отражают реальную практику.")

    w.title("Исходы по сторонам спора")
    w.table(["Кто с кем судится", *OUTCOME_HEADER], outcome_rows(outcome_table(decisions, side_group)))
    w.note(RULE_NOTE)

    counter = [d for d in decisions if d.counter_outcome]
    if counter:
        w.note(f"Встречный иск был в {len(counter)} решениях. Во всех таблицах исход — это исход основного иска; "
               "исход встречного — в листе «Решения».")

    w.title("Исходы по предмету спора")
    w.table(["Предмет спора", *OUTCOME_HEADER], outcome_rows(outcome_table(decisions, lambda d: d.topic or "—")))

    names = court_names(decisions)
    w.title("Исходы по судам")
    w.table(["Суд", *OUTCOME_HEADER],
            outcome_rows(outcome_table(decisions, lambda d: names.get(court_key(d), d.court or "—"))))

    w.title("Порядок рассмотрения")
    w.table(["Порядок", *OUTCOME_HEADER],
            outcome_rows(outcome_table(decisions, lambda d: d.procedure or "не определён")))

    w.title("Взысканные суммы (решения, где взыскан основной долг), тенге")
    money = money_stats(decisions)
    if money:
        w.table(["Показатель", "Значение"], [
            ["Решений со взысканием долга", money.decisions],
            ["Основной долг: всего", money.principal_total],
            ["Основной долг: минимум", money.principal_min],
            ["Основной долг: медиана", money.principal_median],
            ["Основной долг: максимум", money.principal_max],
            ["Неустойка, пеня: всего", money.penalty_total],
            ["Госпошлина: всего", money.state_fee_total],
            ["Услуги представителя: всего", money.lawyer_total],
            ["Прочие расходы (почта, экспертиза, нотариус): всего", money.other_total],
        ])
    else:
        w.note("Нет решений со взысканием долга в пользу ОСИ.")

    w.title("Взыскано с самого ОСИ, тенге")
    pays = osi_pays_stats(decisions)
    if pays:
        w.table(["Показатель", "Значение"], [
            ["Решений, где суд взыскал деньги с ОСИ", pays.decisions],
            ["Всего взыскано с ОСИ", pays.total],
            ["из них услуги представителя", pays.lawyer_total],
            ["из них госпошлина", pays.state_fee_total],
        ])
    else:
        w.note("Нет решений, где деньги взысканы с ОСИ.")
    w.note("Суммы выше разделены по строкам «Взыскать с … в пользу …»: в пользу ОСИ и с ОСИ считаются отдельно.")

    w.title("Чаще всего применяемые нормы (без процессуальных статей ГПК) — топ-15")
    w.table(["Закон", "Статья", "Решений", *MAIN_OUTCOMES], [
        [r.citation.law, r.citation.article, r.decisions, *(r.outcomes[o] for o in MAIN_OUTCOMES)]
        for r in article_table(decisions)[:15]
    ])
    w.finish()

    _table_sheet(wb, "Решения", [
        "Номер дела", "Дата", "Суд", "Судья", "Порядок", "Истец", "Ответчики", "Роль ОСИ", "Против кого",
        "Предмет спора", "Требования истца", "Исход (основной иск)", "Встречный иск: исход", "Резолютивная часть (начало)",
        "В пользу ОСИ: долг, ₸", "В пользу ОСИ: неустойка, ₸", "В пользу ОСИ: госпошлина, ₸",
        "В пользу ОСИ: представитель, ₸", "В пользу ОСИ: прочие расходы, ₸",
        "С ОСИ: всего, ₸", "Между другими участниками: всего, ₸",
        "Пунктов «Обязать/Признать»", "Нормы права", "Постановления ВС", "Предупреждения", "Файл",
    ], [
        [
            d.case_number, d.date, d.court, d.judge, d.procedure,
            "; ".join(display_party(p) for p in d.plaintiffs),
            "; ".join(display_party(p) for p in d.defendants),
            d.osi_role, d.opponent, d.topic, d.claim[:300], d.outcome, d.counter_outcome or "—", d.outcome_text[:300],
            d.amounts.principal, d.amounts.penalty, d.amounts.state_fee, d.amounts.lawyer, d.amounts.other_costs,
            d.osi_pays.total, d.other_awards.total,
            d.obligations,
            "; ".join(f"{c.law} ст. {c.article}" for c in d.citations if not c.procedural),
            "; ".join(d.resolutions), "; ".join(d.warnings), d.file,
        ]
        for d in decisions
    ])

    _table_sheet(wb, "Нормы права", ["Закон", "Статья", "Решений", *MAIN_OUTCOMES, "Процессуальная"], [
        [r.citation.law, r.citation.article, r.decisions, *(r.outcomes[o] for o in MAIN_OUTCOMES),
         "да" if procedural else "нет"]
        for procedural in (False, True)
        for r in article_table(decisions, procedural=procedural)
    ])

    _table_sheet(wb, "Исключено", ["Файл", "Номер дела", "Причина"], [
        [e.file, e.case_number, e.reason] for e in result.excluded
    ] + [[name, "", f"не прочитан: {err}"] for name, err in result.errors])

    _table_sheet(wb, "Нераспознанные ссылки", ["Номер дела", "Фрагмент текста"], [
        [d.case_number, frag] for d in decisions for frag in d.unresolved_citations
    ])

    wb.save(path)
    return path


def _period(decisions) -> str:
    dates = [d.date for d in decisions if d.date]
    if not dates:
        return "—"
    return f"{min(dates):%d.%m.%Y} – {max(dates):%d.%m.%Y}"
