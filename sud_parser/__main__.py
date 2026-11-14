"""Запуск из командной строки:

    python -m sud_parser --input input/debtors_example.csv --source mock
    python -m sud_parser --input input/debtors.csv --source portal-sot.kz --courts 197142
    python -m sud_parser --list-courts Астан
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from .export import write_report
from .http_client import PoliteClient
from .input_reader import read_debtors
from .pipeline import run
from .sources import SOURCES, MockSource, PortalSotSource
from .sources.portal_sot_kz import DEFAULT_COURTS, fetch_courts
from .storage import Storage


def setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return log_file


def list_courts(name_part: str) -> int:
    """Показать коды судов, в названии которых есть name_part (например, «Астан»)."""
    client = PoliteClient()
    try:
        courts = fetch_courts(client)
    finally:
        client.close()
    part = name_part.lower()
    found = [c for c in courts if part in (c.get("VALUE_RU") or "").lower()]
    for c in found:
        print(f"{c['CODE']}  {c['VALUE_RU']}")
    print(f"Найдено судов: {len(found)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # чтобы кириллица не ломалась в консоли Windows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(prog="sud_parser", description="Поиск судебных дел по должникам ОСИ")
    p.add_argument("--input", help="CSV/XLSX со списком должников")
    p.add_argument("--source", default="mock", choices=sorted(SOURCES), help="источник данных")
    p.add_argument("--db", default="data/cases.db", help="файл базы SQLite")
    p.add_argument("--out", default="reports", help="папка для Excel-отчётов")
    p.add_argument("--mock-day", type=int, default=0, help="только для mock: имитация сдвига во времени")
    p.add_argument("--courts", default=",".join(DEFAULT_COURTS),
                   help="portal-sot.kz: коды судов через запятую (см. --list-courts)")
    p.add_argument("--days-back", type=int, default=7, help="portal-sot.kz: сколько дней назад смотреть")
    p.add_argument("--days-ahead", type=int, default=7, help="portal-sot.kz: сколько дней вперёд смотреть")
    p.add_argument("--list-courts", metavar="ЧАСТЬ_НАЗВАНИЯ",
                   help="показать коды судов portal-sot.kz по части названия и выйти")
    args = p.parse_args(argv)

    if args.list_courts is not None:
        return list_courts(args.list_courts)
    if not args.input:
        p.error("нужен --input (файл со списком должников)")

    log_file = setup_logging(Path("logs"))
    log = logging.getLogger("sud_parser")

    inp = read_debtors(args.input)
    for err in inp.errors:
        log.warning("Входной файл, %s", err)
    if not inp.debtors:
        log.error("Во входном файле нет корректных записей")
        return 1
    log.info("Загружено должников: %d (отклонено строк: %d)", len(inp.debtors), len(inp.errors))

    if args.source == MockSource.name:
        source = MockSource(day=args.mock_day)
    else:
        courts = [c.strip() for c in args.courts.split(",") if c.strip()]
        source = PortalSotSource(courts=courts, days_back=args.days_back, days_ahead=args.days_ahead)

    storage = Storage(args.db)
    try:
        result = run(inp.debtors, source, storage)
        report = write_report(result, storage, args.out)
    finally:
        source.close()
        storage.close()

    log.info(
        "Готово. Найдено дел: %d, новых: %d, сменили статус: %d, ошибок: %d",
        result.cases_found, result.new_cases, result.changed, len(result.errors),
    )
    log.info("Отчёт: %s", report)
    log.info("Журнал: %s", log_file)
    return 0 if not result.errors else 2


if __name__ == "__main__":
    sys.exit(main())
