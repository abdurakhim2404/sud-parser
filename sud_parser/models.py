"""Модели данных: что парсер получает на вход и что отдаёт на выход."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Debtor:
    """ВХОД: один должник из списка ОСИ."""

    iin: str | None = None          # ИИН, 12 цифр — основной ключ поиска
    full_name: str | None = None    # ФИО — запасной ключ поиска
    osi_bin: str | None = None      # БИН ОСИ (истец)
    apartment: str | None = None    # номер квартиры
    debt_kzt: float | None = None   # сумма долга по данным ОСИ

    @property
    def label(self) -> str:
        """Безопасная подпись для логов: ИИН замаскирован."""
        if self.iin:
            return mask_iin(self.iin)
        if self.full_name:  # "ЖУМАБАЕВ АРМАН КАЙРАТОВИЧ" -> "ЖУМАБАЕВ А. К."
            surname, *rest = self.full_name.split()
            return " ".join([surname] + [p[0] + "." for p in rest])
        return "<без данных>"


@dataclass
class CourtCase:
    """ВЫХОД: одно найденное судебное дело."""

    source: str                      # откуда взяли: "portal-sot.kz", "mock", ...
    case_number: str                 # номер дела — вместе с source даёт уникальный ключ
    court: str | None = None         # наименование суда
    category: str | None = None      # категория дела
    parties: str | None = None       # стороны (истец / ответчик)
    amount_kzt: float | None = None  # сумма иска
    status: str | None = None        # стадия: принято, назначено, решение вынесено...
    case_date: str | None = None     # дата в формате ГГГГ-ММ-ДД
    url: str | None = None           # ссылка на карточку дела
    matched_by: str = "iin"          # как нашли: "iin" (точно) или "name" (нужна проверка)


def mask_iin(iin: str) -> str:
    """900101300123 -> 9001******23. ИИН — персональные данные, в логи целиком не пишем."""
    if len(iin) < 6:
        return "*" * len(iin)
    return iin[:4] + "*" * (len(iin) - 6) + iin[-2:]
