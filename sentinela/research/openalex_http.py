"""Cursor-based OpenAlex works HTTP client."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class OpenAlexHttpError(RuntimeError):
    pass


class OpenAlexTransportError(OpenAlexHttpError):
    pass


class OpenAlexResponseError(OpenAlexHttpError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"OpenAlex request failed with HTTP {status_code}")
        self.status_code = status_code


class OpenAlexRateLimitError(OpenAlexResponseError):
    def __init__(self, retry_after_seconds: float | None) -> None:
        super().__init__(429)
        self.retry_after_seconds = retry_after_seconds


class OpenAlexProtocolError(OpenAlexHttpError):
    pass


@dataclass(frozen=True)
class OpenAlexWorksPage:
    results: tuple[dict[str, Any], ...]
    next_cursor: str | None
    total_count: int | None = None


class OpenAlexWorksClient:
    def __init__(
        self,
        *,
        mailto: str,
        base_url: str = "https://api.openalex.org",
        user_agent: str = "sentinela-hl/0.1",
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        client: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not mailto.strip():
            raise ValueError("mailto must not be blank")
        if timeout_seconds <= 0 or max_attempts < 1 or backoff_seconds < 0:
            raise ValueError("invalid HTTP retry configuration")
        self._mailto = mailto.strip()
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent.strip()
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._client = client if client is not None else httpx.Client(
            timeout=timeout_seconds, follow_redirects=True
        )
        self._sleeper = sleeper
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch_works_page(
        self,
        *,
        filters: str,
        cursor: str = "*",
        per_page: int = 200,
        select: str | None = None,
    ) -> OpenAlexWorksPage:
        if not filters.strip():
            raise ValueError("filters must not be blank")
        if not cursor:
            raise ValueError("cursor must not be blank")
        if not 1 <= per_page <= 200:
            raise ValueError("per_page must be between 1 and 200")
        params: dict[str, str | int] = {
            "filter": filters,
            "cursor": cursor,
            "per-page": per_page,
            "mailto": self._mailto,
        }
        if select is not None:
            params["select"] = select
        response = self._request(params)
        try:
            body = response.json()
        except (ValueError, TypeError, AttributeError):
            raise OpenAlexProtocolError("OpenAlex response is not valid JSON") from None
        if not isinstance(body, dict):
            raise OpenAlexProtocolError("OpenAlex response must be an object")
        results = body.get("results")
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise OpenAlexProtocolError("OpenAlex results must be a list of objects")
        meta = body.get("meta", {})
        if not isinstance(meta, dict):
            raise OpenAlexProtocolError("OpenAlex meta must be an object")
        next_cursor = meta.get("next_cursor")
        if next_cursor == "":
            next_cursor = None
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise OpenAlexProtocolError("OpenAlex next_cursor is invalid")
        count = meta.get("count")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 0
        ):
            raise OpenAlexProtocolError("OpenAlex count is invalid")
        return OpenAlexWorksPage(tuple(results), next_cursor, count)

    def iter_works(
        self,
        *,
        filters: str,
        cursor: str = "*",
        per_page: int = 200,
        select: str | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive")
        current = cursor
        seen = {current}
        pages = 0
        while True:
            page = self.fetch_works_page(
                filters=filters, cursor=current, per_page=per_page, select=select
            )
            pages += 1
            yield from page.results
            if page.next_cursor is None or (max_pages is not None and pages >= max_pages):
                return
            if page.next_cursor in seen:
                raise OpenAlexProtocolError("OpenAlex cursor repeated")
            seen.add(page.next_cursor)
            current = page.next_cursor

    def _request(self, params: dict[str, str | int]) -> Any:
        retry_after: float | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(
                    f"{self._base_url}/works",
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": f"{self._user_agent} (mailto:{self._mailto})",
                    },
                    timeout=self._timeout,
                    follow_redirects=True,
                )
            except httpx.TooManyRedirects:
                raise OpenAlexTransportError("OpenAlex redirect limit exceeded") from None
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self._max_attempts:
                    raise OpenAlexTransportError(
                        f"OpenAlex transport failed: {type(exc).__name__}"
                    ) from None
                self._sleeper(self._backoff_delay(attempt))
                continue
            status = response.status_code
            if status < 400:
                return response
            if status not in _RETRYABLE_STATUS:
                raise OpenAlexResponseError(status)
            if status == 429:
                retry_after = self._retry_after(response.headers.get("Retry-After"))
            if attempt == self._max_attempts:
                if status == 429:
                    raise OpenAlexRateLimitError(retry_after)
                raise OpenAlexResponseError(status)
            self._sleeper(
                retry_after if retry_after is not None else self._backoff_delay(attempt)
            )
        raise AssertionError("unreachable")

    def _backoff_delay(self, attempt: int) -> float:
        return self._backoff * (2 ** (attempt - 1))

    def _retry_after(self, value: str | None) -> float | None:
        if value is None:
            return None
        try:
            seconds = float(value)
            return max(0.0, seconds)
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            return max(0.0, (retry_at - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
