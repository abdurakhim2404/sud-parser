"""Источник: «График рассмотрения судебных дел» Единого портала судебных органов (portal-sot.kz).

Открытый раздел: без входа и без капчи. Портал отдаёт JSON:

    GET /api/public/schedule/find/{код суда}/{инстанция}/{вид дел}/{ГГГГ-ММ-ДД}

Как работает источник:
1. Один раз скачивает графики выбранных судов за период (суды × дни = число запросов).
2. Ищет каждого должника среди ОТВЕТЧИКОВ по полному ФИО.

Ограничения (важно понимать и уметь объяснить):
- портал отдаёт не больше 50 дел на один запрос (суд + день), и сам сайт показывает столько же;
  в крупных судах это только часть заседаний, поэтому «не найдено» НЕ значит «заседания нет»;
- в графике только назначенные заседания; приказное производство без заседания сюда не попадает;
- в графике нет ИИН, поэтому совпадение только по ФИО -> всегда пометка «нужна проверка»
  (возможны полные тёзки);
- статуса дела нет; статус формируем сами: «Заседание ДД.ММ.ГГГГ ЧЧ:ММ».
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from ..http_client import PoliteClient
from ..input_reader import normalize_name
from ..models import CourtCase, Debtor
from .base import Source

log = logging.getLogger(__name__)

BASE_URL = "https://portal-sot.kz"
API = BASE_URL + "/api/public"

# Межрайонный суд по гражданским делам г. Астаны. Другие коды: python -m sud_parser --list-courts
DEFAULT_COURTS = ("197142",)
PAGE_CAP = 50  # проверено 13.11.2026: 33 из 40 запросов вернули ровно 50 дел, больше — ни один


def _api_data(response) -> list:
    """Портал всегда отвечает {"status": 0, "data": [...]}; status != 0 — ошибка."""
    body = response.json()
    if body.get("status") != 0:
        raise RuntimeError(f"портал вернул ошибку: {body.get('message') or body.get('messageRu')}")
    return body.get("data") or []


def fetch_courts(client: PoliteClient) -> list[dict]:
    """Справочник всех судов: [{'CODE': '197142', 'VALUE_RU': '...', ...}, ...]."""
    return _api_data(client.get(f"{API}/dictionary/court/search"))


class PortalSotSource(Source):
    name = "portal-sot.kz"

    def __init__(
        self,
        courts: tuple[str, ...] | list[str] = DEFAULT_COURTS,
        days_back: int = 7,
        days_ahead: int = 7,
        instance: str = "FIRSTINSTANCE",
        case_type: str = "CIVIL",
        client: PoliteClient | None = None,
        today: date | None = None,
    ):
        self.courts = list(courts)
        self.days_back = days_back
        self.days_ahead = days_ahead
        self.instance = instance
        self.case_type = case_type
        self.client = client or PoliteClient(min_interval=2.0)
        self.today = today or date.today()
        # ФИО ответчика -> {номер дела: CourtCase}; заполняется при первом поиске
        self._by_defendant: dict[str, dict[str, CourtCase]] | None = None
        self._load_error: Exception | None = None
        self.requests = 0            # сколько графиков (суд + день) запрошено
        self.capped_requests = 0     # сколько из них упёрлись в лимит 50 дел, то есть неполные

    def _dates(self) -> list[date]:
        days = [self.today + timedelta(days=n) for n in range(-self.days_back, self.days_ahead + 1)]
        return [d for d in days if d.weekday() < 5]  # в выходные заседаний нет — не тратим запросы

    def _court_names(self) -> dict[str, str]:
        try:
            return {c["CODE"]: c["VALUE_RU"] for c in fetch_courts(self.client)}
        except Exception as exc:  # без названий работать можно — покажем код суда
            log.warning("Не удалось получить справочник судов: %s", exc)
            return {}

    def _load(self) -> None:
        index: dict[str, dict[str, CourtCase]] = {}
        names = self._court_names()
        dates = self._dates()
        log.info("portal-sot.kz: загружаю графики, судов: %d, дней: %d (запросов: %d)",
                 len(self.courts), len(dates), len(self.courts) * len(dates))
        hearings = 0
        for court in self.courts:
            for day in dates:  # по возрастанию: более позднее заседание заменяет раннее
                url = f"{API}/schedule/find/{court}/{self.instance}/{self.case_type}/{day.isoformat()}"
                items = _api_data(self.client.get(url))
                self.requests += 1
                if len({i.get("caseNumber") for i in items}) >= PAGE_CAP:
                    self.capped_requests += 1
                for item in items:
                    hearings += 1
                    case = self._to_case(item, day, names.get(court, f"Суд {court}"))
                    if case is None:
                        continue
                    for person in item.get("defendants") or []:
                        key = normalize_name(person.get("name") or "")
                        if key:
                            index.setdefault(key, {})[case.case_number] = case
        log.info("portal-sot.kz: заседаний в графиках: %d", hearings)
        if self.capped_requests:
            log.warning(
                "portal-sot.kz: %d из %d графиков неполные (портал отдаёт не больше %d дел на суд и день). "
                "«Дел не найдено» не значит, что заседания нет.",
                self.capped_requests, self.requests, PAGE_CAP)
        self._by_defendant = index

    @staticmethod
    def _to_case(item: dict, day: date, court_name: str) -> CourtCase | None:
        number = (item.get("caseNumber") or "").strip()
        if not number:
            return None

        def joined(key: str) -> str:
            return ", ".join(p.get("name", "").strip() for p in item.get(key) or [] if p.get("name"))

        details = [f"Заседание {day:%d.%m.%Y} {item.get('time') or ''}".strip()]
        if item.get("hallNumber"):
            details.append(f"зал {item['hallNumber']}")
        if item.get("judge"):
            details.append(f"судья {item['judge']}")
        return CourtCase(
            source=PortalSotSource.name,
            case_number=number,
            court=court_name,
            category="Гражданское дело",
            parties=f"{joined('applicants') or '—'} к {joined('defendants') or '—'}",
            status=", ".join(details),
            case_date=day.isoformat(),
            url=f"{BASE_URL}/schedule",
            matched_by="name",
        )

    def search(self, debtor: Debtor) -> list[CourtCase]:
        if not debtor.full_name:
            raise ValueError("в графике заседаний нет ИИН — для поиска нужно ФИО")
        if self._load_error:  # графики не загрузились — не дёргаем портал заново для каждого должника
            raise self._load_error
        if self._by_defendant is None:
            try:
                self._load()
            except Exception as exc:
                self._load_error = RuntimeError(f"не удалось загрузить графики заседаний: {exc}")
                raise self._load_error from exc
        return list(self._by_defendant.get(normalize_name(debtor.full_name), {}).values())

    def close(self) -> None:
        self.client.close()
