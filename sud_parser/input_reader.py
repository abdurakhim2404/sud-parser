"""Чтение и проверка входного файла со списком должников (CSV или Excel)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import Debtor

COLUMNS = ("iin", "full_name", "osi_bin", "apartment", "debt_kzt")


@dataclass
class InputResult:
    debtors: list[Debtor] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # "строка 5: неверный ИИН"


def is_valid_iin(value: str) -> bool:
    """Проверка ИИН/БИН РК: 12 цифр + контрольный разряд.

    Контрольная цифра = сумма(цифра_i * вес_i) mod 11, веса 1..11.
    Если получилось 10 — считаем со вторым набором весов 3..11,1,2.
    Если снова 10 — номер недействителен.
    """
    if not re.fullmatch(r"\d{12}", value):
        return False
    digits = [int(c) for c in value]
    weights_1 = list(range(1, 12))
    weights_2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]
    control = sum(d * w for d, w in zip(digits, weights_1)) % 11
    if control == 10:
        control = sum(d * w for d, w in zip(digits, weights_2)) % 11
        if control == 10:
            return False
    return control == digits[11]


def normalize_name(name: str) -> str:
    """'  иванов   иван ' -> 'ИВАНОВ ИВАН' (ё -> е), чтобы сравнение не зависело от записи."""
    return re.sub(r"\s+", " ", name).strip().upper().replace("Ё", "Е")


def _read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        sheet = load_workbook(path, read_only=True, data_only=True).active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(h or "").strip().lower() for h in rows[0]]
        return [
            {header[i]: ("" if v is None else str(v)) for i, v in enumerate(r) if i < len(header)}
            for r in rows[1:]
        ]

    # CSV: utf-8-sig убирает BOM, который добавляет Excel; разделитель определяем сами (; или ,)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        return []
    delimiter = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    return [{(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader]


def read_debtors(path: str | Path) -> InputResult:
    path = Path(path)
    result = InputResult()
    seen: set[str] = set()

    for line_no, row in enumerate(_read_rows(path), start=2):  # строка 1 — заголовок
        iin = re.sub(r"\D", "", row.get("iin", "")) or None
        name = normalize_name(row.get("full_name", "")) or None

        if not iin and not name:
            if any(v.strip() for v in row.values()):
                result.errors.append(f"строка {line_no}: нет ни ИИН, ни ФИО")
            continue
        if iin and not is_valid_iin(iin):
            result.errors.append(f"строка {line_no}: неверный ИИН (не прошёл проверку контрольной цифры)")
            continue

        key = iin or name
        if key in seen:
            result.errors.append(f"строка {line_no}: дубль, пропущен")
            continue
        seen.add(key)

        debt_raw = row.get("debt_kzt", "").replace(" ", "").replace(",", ".")
        try:
            debt = float(debt_raw) if debt_raw else None
        except ValueError:
            result.errors.append(f"строка {line_no}: сумма долга не число, оставлена пустой")
            debt = None

        result.debtors.append(
            Debtor(
                iin=iin,
                full_name=name,
                osi_bin=re.sub(r"\D", "", row.get("osi_bin", "")) or None,
                apartment=row.get("apartment", "").strip() or None,
                debt_kzt=debt,
            )
        )
    return result
