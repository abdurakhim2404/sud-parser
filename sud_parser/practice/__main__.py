"""Анализ судебной практики по папке с решениями:

    python -m sud_parser.practice --dir "C:\\Users\\Admin\\Documents\\sud-decisions"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyze import analyze_folder, outcome_table, side_group
from .report import write_practice_report


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(prog="sud_parser.practice",
                                description="Анализ судебной практики по текстам решений (.docx, .txt)")
    p.add_argument("--dir", required=True, help="папка с файлами решений")
    p.add_argument("--out", default="reports", help="папка для Excel-отчёта")
    args = p.parse_args(argv)

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f"Папка не найдена: {folder}")
        return 2

    result = analyze_folder(folder)
    report = write_practice_report(result, args.out, source=str(folder))

    print(f"Файлов: {result.files_total}, решений в анализе: {len(result.decisions)}, "
          f"исключено: {len(result.excluded)}, не прочитано: {len(result.errors)}")
    for row in outcome_table(result.decisions, side_group):
        print(f"  {row.label}: {row.total} реш.; ОСИ выиграло {row.won}, частично {row.partly}, проиграло {row.lost}")
    flagged = [d for d in result.decisions if d.warnings]
    if flagged:
        print(f"Проверить вручную ({len(flagged)}):")
        for d in flagged:
            print(f"  {d.case_number or d.file}: {'; '.join(d.warnings)}")
    print(f"Отчёт: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
