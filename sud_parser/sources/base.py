"""Общий интерфейс источника данных.

Каждый сайт (portal-sot.kz, aisoip.adilet.gov.kz, ...) — отдельный класс-наследник Source.
Остальная программа (база, отчёты, мониторинг) не знает, откуда пришли данные,
поэтому новый источник добавляется без изменения остального кода.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import CourtCase, Debtor


class Source(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, debtor: Debtor) -> list[CourtCase]:
        """Найти все дела по должнику. Пустой список = дел нет. Исключение = ошибка поиска."""

    def close(self) -> None:
        """Освободить ресурсы (HTTP-сессию, браузер)."""
