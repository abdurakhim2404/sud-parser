"""Обезличенные демо-данные: разобранные решения без ФИО — для окна в интернете.

    python -m sud_parser.practice.demo <папка> [<папка> …] --out demo/decisions.json

В файл попадают только результаты разбора: исход, суммы, нормы права, суд, номер дела.
Самих текстов решений там нет. ФИО физлиц заменены инициалами, имена файлов — номерами дел.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .analyze import Excluded, PracticeResult, analyze_folders
from .extract import PERSON, Amounts, Citation, Decision, display_party, mask_person, party_kind

DEMO_FILE = Path(__file__).resolve().parents[2] / "demo" / "decisions.json"


def _file_name(d: Decision) -> str:
    """Имя файла по номеру дела: исходные имена файлов бывают с фамилиями сторон."""
    suffix = Path(d.file).suffix.lower() or ".docx"
    return (re.sub(r"[^0-9A-Za-z-]+", "_", d.case_number).strip("_") or "дело") + suffix


def _party(name: str) -> str:
    return mask_person(name) if party_kind(name) == PERSON else display_party(name)


def to_public(d: Decision) -> dict:
    data = asdict(d)
    data.update(
        file=_file_name(d),
        date=d.date.isoformat() if d.date else None,
        plaintiffs=[_party(p) for p in d.plaintiffs],
        defendants=[_party(p) for p in d.defendants],
        third_parties=[_party(p) for p in d.third_parties],
        claim=d.masked(d.claim[:600]),
        outcome_text=d.masked(d.outcome_text[:600]),
        unresolved_citations=[d.masked(f) for f in d.unresolved_citations],
    )
    return data


def from_public(data: dict) -> Decision:
    data = dict(data)
    data["date"] = date.fromisoformat(data["date"]) if data.get("date") else None
    for key in ("amounts", "osi_pays", "other_awards"):
        data[key] = Amounts(**data[key])
    data["citations"] = [Citation(**c) for c in data["citations"]]
    return Decision(**data)


def save(result: PracticeResult, path: Path, source: str) -> int:
    payload = {
        "source": source,
        "files_total": result.files_total,
        "decisions": [to_public(d) for d in result.decisions],
        # исключённые: только номер дела и причина (имена файлов и текст причины — без ФИО)
        "excluded": [{"file": "", "case_number": e.case_number, "reason": e.reason.split("«")[0].strip()}
                     for e in result.excluded],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(payload["decisions"])


def load(path: Path = DEMO_FILE) -> tuple[PracticeResult, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = PracticeResult(
        decisions=[from_public(x) for x in payload["decisions"]],
        excluded=[Excluded(**e) for e in payload["excluded"]],
        files_total=payload["files_total"],
    )
    return result, payload["source"]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="sud_parser.practice.demo", description="Обезличенные демо-данные")
    p.add_argument("folders", nargs="+", help="папки с решениями")
    p.add_argument("--out", default=str(DEMO_FILE))
    p.add_argument("--source", default="", help="описание выборки для окна")
    args = p.parse_args(argv)
    result = analyze_folders([Path(f) for f in args.folders])
    n = save(result, Path(args.out), args.source or f"{len(args.folders)} папок")
    print(f"Решений: {n} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
