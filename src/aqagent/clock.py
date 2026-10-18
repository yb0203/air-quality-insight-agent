"""The only module allowed to read wall-clock time. Everything else receives a Clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    def __init__(self, t: datetime):
        if t.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._t = t

    def now(self) -> datetime:
        return self._t

    def set(self, t: datetime) -> None:
        self._t = t

    def advance(self, delta: timedelta) -> None:
        self._t = self._t + delta
