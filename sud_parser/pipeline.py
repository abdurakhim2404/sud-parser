"""Основной цикл: для каждого должника — поиск, сохранение, учёт изменений."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .models import CourtCase, Debtor
from .sources.base import Source
from .storage import CHANGED, NEW, Storage

log = logging.getLogger(__name__)


@dataclass
class Change:
    debtor: Debtor
    case: CourtCase
    kind: str                 # "new" или "changed"
    old_status: str | None


@dataclass
class RunResult:
    debtors: int = 0
    cases_found: int = 0
    not_found: int = 0
    changes: list[Change] = field(default_factory=list)
    errors: list[tuple[Debtor, str]] = field(default_factory=list)

    @property
    def new_cases(self) -> int:
        return sum(c.kind == NEW for c in self.changes)

    @property
    def changed(self) -> int:
        return sum(c.kind == CHANGED for c in self.changes)


def run(debtors: list[Debtor], source: Source, storage: Storage) -> RunResult:
    result = RunResult(debtors=len(debtors))
    run_id = storage.start_run(source.name)

    for i, debtor in enumerate(debtors, start=1):
        try:
            cases = source.search(debtor)
        except Exception as exc:  # ошибка по одному должнику не останавливает весь прогон
            log.error("[%d/%d] %s: ошибка поиска: %s", i, len(debtors), debtor.label, exc)
            result.errors.append((debtor, str(exc)))
            continue

        if not cases:
            result.not_found += 1
        for case in cases:
            outcome, old_status = storage.save_case(case, debtor)
            if outcome in (NEW, CHANGED):
                result.changes.append(Change(debtor, case, outcome, old_status))
        result.cases_found += len(cases)
        log.info("[%d/%d] %s: найдено дел — %d", i, len(debtors), debtor.label, len(cases))

    storage.finish_run(
        run_id,
        debtors=result.debtors,
        cases_found=result.cases_found,
        new_cases=result.new_cases,
        changed=result.changed,
        errors=len(result.errors),
    )
    return result
