"""S1: OpenAQ v3 client (S-A §1). Hourly series only; respects rate limits; never logs the API key."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from aqagent import params
from aqagent.types import Reading

log = logging.getLogger(__name__)
UTC = timezone.utc

BASE_URL = "https://api.openaq.org/v3"
MAX_TRIES = 3  # per request, on 429 (plan Task 3)
DEFAULT_RESET_S = 60.0  # when a 429 carries no x-ratelimit-reset: wait out the per-minute window (S-A §1)


class MissingAPIKey(RuntimeError):
    """OPENAQ_API_KEY is empty: fail fast, before any call is made."""


class OpenAQError(RuntimeError):
    """A failed OpenAQ request. The message never contains the API key."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _fmt(t: datetime) -> str:
    if t.tzinfo is None:
        raise ValueError("OpenAQ query times must be timezone-aware")
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _header_float(resp: httpx.Response, name: str) -> float | None:
    try:
        return float(resp.headers[name])
    except (KeyError, ValueError):
        return None


class OpenAQClient:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, base_url: str = BASE_URL):
        if not api_key or not api_key.strip():
            raise MissingAPIKey("OPENAQ_API_KEY is not set; live ingestion needs a key from explore.openaq.org")
        self._key = api_key.strip()
        self._sleep = sleep
        self._http = httpx.Client(base_url=base_url, transport=transport, headers={"X-API-Key": self._key})
        self.last_ratelimit_remaining: int | None = None
        self._pause_s: float | None = None  # set when the quota hit 0: wait for the reset before the next call

    def __repr__(self) -> str:
        return f"OpenAQClient(base_url={str(self._http.base_url)!r})"

    def close(self) -> None:
        self._http.close()

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***")

    def _get(self, path: str, query: dict) -> dict:
        for attempt in range(1, MAX_TRIES + 1):
            if self._pause_s:
                log.info("OpenAQ quota exhausted; waiting %.0fs for the reset", self._pause_s)
                self._sleep(self._pause_s)
                self._pause_s = None
            log.debug("GET %s page=%s (try %d)", path, query.get("page"), attempt)
            try:
                resp = self._http.get(path, params=query)
            except httpx.HTTPError as e:
                raise OpenAQError(self._redact(f"GET {path} failed: {type(e).__name__}: {e}")) from None
            remaining = _header_float(resp, "x-ratelimit-remaining")
            if remaining is not None:
                self.last_ratelimit_remaining = int(remaining)
            reset = _header_float(resp, "x-ratelimit-reset")
            if resp.status_code == 429:
                if attempt == MAX_TRIES:
                    break
                wait = reset if reset is not None else DEFAULT_RESET_S
                log.warning("OpenAQ 429 on %s; backing off %.0fs (try %d of %d)", path, wait, attempt, MAX_TRIES)
                self._sleep(wait)
                continue
            if resp.status_code >= 400:
                raise OpenAQError(self._redact(f"GET {path} returned HTTP {resp.status_code}"), resp.status_code)
            if remaining == 0:
                self._pause_s = reset if reset is not None else DEFAULT_RESET_S
            return resp.json()
        raise OpenAQError(f"GET {path} returned HTTP 429 {MAX_TRIES} times; giving up", 429)

    def hours(self, sensor_id: int, dt_from: datetime, dt_to: datetime) -> list[Reading]:
        """Hourly values with dt_from < period end <= dt_to, paging through `limit=1000`. Gaps stay gaps."""
        path = f"/sensors/{sensor_id}/hours"
        out: list[Reading] = []
        page = 1
        while True:
            body = self._get(path, {"datetime_from": _fmt(dt_from), "datetime_to": _fmt(dt_to),
                                    "limit": params.PAGE_LIMIT, "page": page})
            results = body.get("results") or []
            for row in results:
                period = row["period"]
                value = row.get("value")
                cov = (row.get("coverage") or {}).get("percentCoverage")
                out.append(Reading(sensor_id=sensor_id,
                                   period_end=_parse_utc(period["datetimeTo"]["utc"]),
                                   period_start=_parse_utc(period["datetimeFrom"]["utc"]),
                                   value=None if value is None else float(value),
                                   coverage_pct=None if cov is None else float(cov)))
            if len(results) < params.PAGE_LIMIT:
                return out
            page += 1
