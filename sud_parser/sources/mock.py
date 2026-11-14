"""Тестовый источник с выдуманными данными.

Нужен, чтобы проверить всю цепочку (вход -> поиск -> база -> отчёт) без обращения
к реальному сайту суда. Результат детерминированный: один и тот же ИИН всегда
даёт одни и те же дела, а параметр `day` имитирует смену статуса со временем.
"""
from __future__ import annotations

import hashlib

from ..models import CourtCase, Debtor
from .base import Source

STATUSES = ["Принято к производству", "Назначено к рассмотрению", "Решение вынесено", "Решение вступило в силу"]
COURTS = ["Специализированный межрайонный экономический суд г. Астаны", "Районный суд №2 г. Астаны", "Есильский районный суд г. Астаны"]


class MockSource(Source):
    name = "mock"

    def __init__(self, day: int = 0):
        self.day = day  # «сдвиг во времени»: при day=1 часть дел продвинется на следующую стадию

    def search(self, debtor: Debtor) -> list[CourtCase]:
        key = debtor.iin or debtor.full_name or ""
        h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        count = h % 3  # 0, 1 или 2 дела
        cases = []
        for i in range(count):
            seed = (h >> (8 * (i + 1))) & 0xFFFF
            stage = min(seed % 3 + (self.day if seed % 2 else 0), len(STATUSES) - 1)
            cases.append(
                CourtCase(
                    source=self.name,
                    case_number=f"7194-25-00-2/{seed:05d}",
                    court=COURTS[seed % len(COURTS)],
                    category="Взыскание задолженности по взносам на содержание общего имущества",
                    parties=f"ОСИ {debtor.osi_bin or '—'} к {debtor.full_name or debtor.label}",
                    amount_kzt=debtor.debt_kzt or float(50_000 + seed * 3 % 400_000),
                    status=STATUSES[stage],
                    case_date=f"2025-{seed % 12 + 1:02d}-{seed % 28 + 1:02d}",
                    url=None,
                    matched_by="iin" if debtor.iin else "name",
                )
            )
        return cases
