"""График заседаний (data/schedule_sample.json) -> обезличенный Excel для передачи.

    python tools/schedule_to_excel.py data/schedule_sample.json data/drive/grafik.xlsx

ФИО людей заменяются инициалами («физлицо И. И. И.»), названия ОСИ, компаний и госорганов остаются.
Имена судей остаются: это должностные лица, график публикует их открыто.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sud_parser.practice.extract import OSI, display_party, party_kind  # noqa: E402

COURTS = {"197142": "Межрайонный суд по гражданским делам г. Астаны",
          "197119": "Районный суд г. Астаны (код 197119)"}
HEADER = ["Суд", "Дата", "Время", "Номер дела", "Зал", "Судья", "Истцы", "Ответчики", "Роль ОСИ"]


def osi_role(applicants: list[str], defendants: list[str]) -> str:
    roles = [role for role, side in (("истец", applicants), ("ответчик", defendants))
             if any(party_kind(p) == OSI for p in side)]
    return " и ".join(roles) or "нет"


def convert(src: Path, dst: Path) -> tuple[int, int]:
    days = json.loads(src.read_text(encoding="utf-8"))
    wb = Workbook()
    ws = wb.active
    ws.title = "График"
    ws.append(HEADER)
    seen: set[tuple[str, str]] = set()
    for day in sorted(days, key=lambda d: (d["court"], d["date"])):
        for it in day["items"]:
            applicants = [p["name"] if isinstance(p, dict) else p for p in it.get("applicants") or []]
            defendants = [p["name"] if isinstance(p, dict) else p for p in it.get("defendants") or []]
            seen.add((day["court"], it["caseNumber"]))
            ws.append([
                COURTS.get(day["court"], day["court"]), day["date"], it.get("time", ""), it["caseNumber"],
                it.get("hallNumber", ""), it.get("judge", ""),
                "; ".join(display_party(p) for p in applicants),
                "; ".join(display_party(p) for p in defendants),
                osi_role(applicants, defendants),
            ])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    for col, width in zip("ABCDEFGHI", (40, 12, 8, 22, 8, 22, 50, 50, 12)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    info = wb.create_sheet("Описание")
    for row in [
        ["Что это", "Записи открытого «Графика рассмотрения судебных дел» portal-sot.kz"],
        ["Суды", "; ".join(COURTS.values())],
        ["Период", f"{min(d['date'] for d in days)} – {max(d['date'] for d in days)}, рабочие дни"],
        ["Записей", ws.max_row - 1],
        ["Разных дел", len(seen)],
        ["Персональные данные", "ФИО физлиц заменены инициалами; названия ОСИ, компаний и госорганов, "
                                "имена судей оставлены"],
        ["Ограничение", "Портал отдаёт не больше 50 дел на суд и день, поэтому график неполный"],
    ]:
        info.append(row)
    info.column_dimensions["A"].width = 22
    info.column_dimensions["B"].width = 100
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return ws.max_row - 1, len(seen)


if __name__ == "__main__":
    records, cases = convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Записей: {records}, разных дел: {cases} -> {sys.argv[2]}")
