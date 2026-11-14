"""Хранение результатов в SQLite: без дублей и с историей смены статусов."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import CourtCase, Debtor

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    source       TEXT NOT NULL,
    case_number  TEXT NOT NULL,
    debtor_iin   TEXT,
    debtor_name  TEXT,
    court        TEXT,
    category     TEXT,
    parties      TEXT,
    amount_kzt   REAL,
    status       TEXT,
    case_date    TEXT,
    url          TEXT,
    matched_by   TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    PRIMARY KEY (source, case_number)          -- одно дело = одна строка, дублей нет
);
CREATE TABLE IF NOT EXISTS status_history (
    source       TEXT NOT NULL,
    case_number  TEXT NOT NULL,
    status       TEXT,
    seen_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    source       TEXT,
    debtors      INTEGER,
    cases_found  INTEGER,
    new_cases    INTEGER,
    changed      INTEGER,
    errors       INTEGER
);
"""

NEW, CHANGED, SAME = "new", "changed", "same"


class Storage:
    def __init__(self, path: str | Path = "data/cases.db"):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def save_case(self, case: CourtCase, debtor: Debtor) -> tuple[str, str | None]:
        """Сохранить дело. Возвращает (new|changed|same, прежний статус)."""
        now = self._now()
        row = self.conn.execute(
            "SELECT status FROM cases WHERE source=? AND case_number=?",
            (case.source, case.case_number),
        ).fetchone()
        data = asdict(case)

        if row is None:
            self.conn.execute(
                """INSERT INTO cases (source, case_number, debtor_iin, debtor_name, court, category,
                   parties, amount_kzt, status, case_date, url, matched_by, first_seen, last_seen)
                   VALUES (:source, :case_number, :debtor_iin, :debtor_name, :court, :category,
                   :parties, :amount_kzt, :status, :case_date, :url, :matched_by, :now, :now)""",
                {**data, "debtor_iin": debtor.iin, "debtor_name": debtor.full_name, "now": now},
            )
            outcome, old_status = NEW, None
        else:
            old_status = row["status"]
            self.conn.execute(
                """UPDATE cases SET court=:court, category=:category, parties=:parties,
                   amount_kzt=:amount_kzt, status=:status, case_date=:case_date, url=:url,
                   last_seen=:now WHERE source=:source AND case_number=:case_number""",
                {**data, "now": now},
            )
            outcome = CHANGED if old_status != case.status else SAME

        if outcome != SAME:
            self.conn.execute(
                "INSERT INTO status_history (source, case_number, status, seen_at) VALUES (?, ?, ?, ?)",
                (case.source, case.case_number, case.status, now),
            )
        self.conn.commit()
        return outcome, old_status

    def start_run(self, source: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at, source) VALUES (?, ?)", (self._now(), source))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, **stats: int) -> None:
        self.conn.execute(
            """UPDATE runs SET finished_at=?, debtors=?, cases_found=?, new_cases=?, changed=?, errors=?
               WHERE id=?""",
            (self._now(), stats["debtors"], stats["cases_found"], stats["new_cases"],
             stats["changed"], stats["errors"], run_id),
        )
        self.conn.commit()

    def all_cases(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM cases ORDER BY debtor_iin, case_date").fetchall()

    def close(self) -> None:
        self.conn.close()
