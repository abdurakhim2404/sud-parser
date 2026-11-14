"""HTTP-клиент, который бережно относится к сайту: паузы между запросами и повторы при сбоях."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class PoliteClient:
    def __init__(
        self,
        min_interval: float = 2.0,   # не чаще одного запроса в 2 секунды
        max_retries: int = 3,
        timeout: float = 30.0,
        user_agent: str = "sud-parser/0.1 (internship project)",
    ):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(1, self.max_retries + 1):
            self._wait_turn()
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code not in RETRY_STATUSES:
                    response.raise_for_status()
                    return response
                reason = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:  # таймаут, обрыв соединения и т.п.
                reason = type(exc).__name__
            if attempt == self.max_retries:
                raise RuntimeError(f"{method} {url}: не удалось после {attempt} попыток ({reason})")
            pause = self.min_interval * 2 ** attempt  # 4с, 8с, ... — растущая пауза
            log.warning("%s %s: %s, повтор через %.0f с", method, url, reason, pause)
            time.sleep(pause)
        raise AssertionError("unreachable")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self._client.close()
