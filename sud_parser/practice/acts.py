"""Судебные акты в JSON — для других программ (ботов «AI-юрист», «Помощник председателя ОСИ» и т. п.).

    python -m sud_parser.practice.registry --out data/registry --json data/registry/court_acts.json <папки>

Одна запись = одно решение: поля реестра, подробности разбора и полный текст решения без персональных
данных. Описание полей — docs/court_acts_format.md.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from .analyze import osi_result
from .extract import Amounts, Decision, display_party, mask_document

FORMAT_VERSION = "1.0"
_KZ_LETTERS = re.compile(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]")


def language(text: str) -> str:
    """«kk» — решение на казахском, «ru» — на русском (по доле казахских букв)."""
    letters = sum(c.isalpha() for c in text) or 1
    return "kk" if len(_KZ_LETTERS.findall(text)) / letters > 0.01 else "ru"


def _amounts(a: Amounts) -> dict:
    return {"principal": a.principal, "penalty": a.penalty, "state_fee": a.state_fee, "lawyer": a.lawyer,
            "other_costs": a.other_costs, "total": a.total}


def _parties(names: list[str], types: list[str]) -> list[dict]:
    return [{"name": display_party(n), "type": t} for n, t in zip(names, types)]


def read_links(path: Path) -> dict[str, str]:
    """links.csv: номер дела, ссылка на файл на Google Диске (колонка «Ссылка на источник» реестра)."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r[0].strip(): r[1].strip() for r in csv.reader(f) if len(r) >= 2 and r[1].startswith("http")}


def to_record(d: Decision, row: dict, text: str, plaintiff_types: list[str], defendant_types: list[str],
              link: str = "") -> dict:
    """row — строка реестра (колонка -> значение), чтобы JSON и реестр не расходились."""
    parties = d.plaintiffs + d.defendants + d.third_parties
    return {
        "id": row["ID записи"],
        "case_number": d.case_number,
        "court": row["Суд"],
        "region": row["Город / регион"],
        "year": row["Год"],
        "decision_date": row["Дата решения"] or None,
        "instance": row["Инстанция"],
        "proceeding": row["Тип производства"],
        "language": language(text),
        "category_id": row["ID категории"] or None,
        "category": row["Категория"] or None,
        "topic": d.topic or None,
        "plaintiffs": _parties(d.plaintiffs, plaintiff_types),
        "defendants": _parties(d.defendants, defendant_types),
        "third_parties": [display_party(n) for n in d.third_parties],
        "special_proceeding": d.special,
        "claim": row["Предмет спора (требования)"] or None,
        "claim_amount": d.claim_amount,
        "verdict": row["Вердикт"],
        "counterclaim_verdict": d.counter_outcome or None,
        "osi_role": d.osi_role,
        "osi_result": osi_result(d),
        "awarded_total": float(row["Взыскано, тг"]) if row["Взыскано, тг"] else 0.0,
        "awarded_to_osi": _amounts(d.amounts),
        "awarded_from_osi": _amounts(d.osi_pays),
        "awarded_other": _amounts(d.other_awards),
        "operative_part": d.masked(" ".join(d.outcome_text.split())) or None,
        "laws": [{"law": c.law, "article": c.article} for c in d.citations if not c.procedural],
        "procedural_laws": [{"law": c.law, "article": c.article} for c in d.citations if c.procedural],
        "source_url": link or None,
        "file": row["Файл (относительный путь)"],
        "needs_check": row["Примечание"] or None,
        "text": mask_document(text, parties),
    }


def write(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": FORMAT_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "Банк судебных актов portal-sot.kz, решения первой инстанции по спорам с участием ОСИ",
        "personal_data": "ФИО физлиц заменены инициалами; ИИН, телефоны, номера квартир, даты рождения скрыты",
        "count": len(records),
        "decisions": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
