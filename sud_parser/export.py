"""Excel-отчёт: все дела, изменения за прогон, ошибки, сводка."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .pipeline import RunResult
from .storage import NEW, Storage

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")


def _sheet(wb: Workbook, title: str, header: list[str], rows: list[list]) -> None:
    ws = wb.create_sheet(title)
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(header, start=1):  # ширина колонок по содержимому
        longest = max([len(str(col))] + [len(str(r[i - 1] or "")) for r in rows])
        ws.column_dimensions[get_column_letter(i)].width = min(longest + 2, 60)


def write_report(result: RunResult, storage: Storage, out_dir: str | Path = "reports") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsx"

    wb = Workbook()
    wb.remove(wb.active)

    _sheet(wb, "Сводка", ["Показатель", "Значение"], [
        ["Должников в списке", result.debtors],
        ["Найдено дел", result.cases_found],
        ["Должников без дел", result.not_found],
        ["Новых дел", result.new_cases],
        ["Сменился статус", result.changed],
        ["Ошибок поиска", len(result.errors)],
    ])

    _sheet(wb, "Изменения", ["Тип", "ИИН", "ФИО", "Номер дела", "Суд", "Было", "Стало"], [
        ["Новое дело" if c.kind == NEW else "Смена статуса", c.debtor.iin, c.debtor.full_name,
         c.case.case_number, c.case.court, c.old_status, c.case.status]
        for c in result.changes
    ])

    _sheet(wb, "Все дела", ["ИИН", "ФИО", "Номер дела", "Суд", "Категория", "Сумма, ₸", "Статус",
                            "Дата", "Найдено по", "Ссылка", "Источник", "Последняя проверка"], [
        [r["debtor_iin"], r["debtor_name"], r["case_number"], r["court"], r["category"],
         r["amount_kzt"], r["status"], r["case_date"],
         "ИИН" if r["matched_by"] == "iin" else "ФИО (проверить)", r["url"], r["source"], r["last_seen"]]
        for r in storage.all_cases()
    ])

    _sheet(wb, "Ошибки", ["ИИН", "ФИО", "Ошибка"], [
        [d.iin, d.full_name, err] for d, err in result.errors
    ])

    wb.save(path)
    return path
