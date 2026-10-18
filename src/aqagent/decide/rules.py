"""User rules (S-C §8): typed, validated, every field optional with a default."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

import yaml
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, PlainValidator, ValidationError, field_validator, model_validator

from aqagent import params
from aqagent.types import Band, ReasonCode

_SLUGS = {band.slug: band for band in Band}
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _band(value: Any) -> Band:
    if isinstance(value, Band):
        return value
    if isinstance(value, str) and value in _SLUGS:
        return _SLUGS[value]
    raise ValueError(f"band must be one of {sorted(_SLUGS)}, got {value!r}")


def _hhmm(value: Any) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str) and (m := _HHMM.match(value)):
        return time(int(m.group(1)), int(m.group(2)))
    raise ValueError(f"time must be 'HH:MM' (00:00-23:59), got {value!r}")


BandSlug = Annotated[Band, PlainValidator(_band), PlainSerializer(lambda b: b.slug, return_type=str)]
LocalTime = Annotated[time, PlainValidator(_hhmm), PlainSerializer(lambda t: t.strftime("%H:%M"), return_type=str)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Location(_Strict):
    station_id: int


class QuietHours(_Strict):
    """A wall-clock window in station local time. `start > end` crosses midnight; `start == end` is empty."""

    start: LocalTime = time(22, 0)
    end: LocalTime = time(7, 0)
    breakthrough_band: BandSlug = Band.VERY_UNHEALTHY

    def contains(self, local_dt: datetime) -> bool:
        """Whether a station-local wall-clock time falls in [start, end)."""
        t = local_dt.time()
        if self.start < self.end:
            return self.start <= t < self.end
        if self.start > self.end:
            return t >= self.start or t < self.end
        return False

    def end_after(self, local_dt: datetime) -> datetime:
        """The first wall-clock `end` strictly after `local_dt`, in `local_dt`'s zone (DST-aware)."""
        if local_dt.tzinfo is None or local_dt.utcoffset() is None:
            raise ValueError("local_dt must be timezone-aware (station local time)")
        tz, now = local_dt.tzinfo, local_dt.astimezone(timezone.utc)
        for days in (0, 1, 2):
            wall = datetime.combine(local_dt.date() + timedelta(days=days), self.end, tzinfo=tz)
            # Round-trip through UTC so a wall time inside a DST gap becomes a real instant.
            candidate = wall.astimezone(timezone.utc).astimezone(tz)
            if candidate.astimezone(timezone.utc) > now:
                return candidate
        raise AssertionError("unreachable: tomorrow's end is always later")


class CheckIn(_Strict):
    cron: str | None = None

    @field_validator("cron")
    @classmethod
    def _parses(cls, value: str | None) -> str | None:
        if value is not None:
            CronTrigger.from_crontab(value, timezone="UTC")  # raises ValueError if malformed
        return value


class Pace(_Strict):
    base_gap_hours: int = Field(default=params.PACE_BASE_HOURS, gt=0)


class Budget(_Strict):
    max_per_day: int = Field(default=params.BUDGET_PER_DAY, ge=0)


class Rules(_Strict):
    location: Location
    pollutants: list[str] = Field(default_factory=lambda: ["pm25"])
    sensitivity: Literal["low", "default", "high"] = "default"
    relevance_floor: BandSlug = Band.MODERATE
    alert_band: BandSlug | None = None  # filled in: very_unhealthy, or unhealthy when sensitivity is high
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    check_in: CheckIn = Field(default_factory=CheckIn)
    pace: Pace = Field(default_factory=Pace)
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="before")
    @classmethod
    def _default_alert_band(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("alert_band") is None:
            high = data.get("sensitivity") == "high"
            data = {**data, "alert_band": Band.UNHEALTHY if high else Band.VERY_UNHEALTHY}
        return data

    @property
    def k(self) -> float:
        return params.SENSITIVITY_K[self.sensitivity]

    def in_quiet_hours(self, local_dt: datetime) -> bool:
        """`local_dt` must already be in station local time."""
        return self.quiet_hours.contains(local_dt)

    def quiet_end_after(self, local_dt: datetime) -> datetime:
        """The next quiet-hours end strictly after `local_dt`, as a station-local aware datetime."""
        return self.quiet_hours.end_after(local_dt)

    def next_check_in(self, after: datetime, tz: tzinfo | str) -> datetime | None:
        """The first check-in strictly after `after`, in UTC; the cron is read in station local time `tz`."""
        if self.check_in.cron is None:
            return None
        zone = ZoneInfo(tz) if isinstance(tz, str) else tz
        trigger = CronTrigger.from_crontab(self.check_in.cron, timezone=zone)
        fire = trigger.get_next_fire_time(None, after + timedelta(microseconds=1))
        return fire.astimezone(timezone.utc) if fire is not None else None


class Persona(_Strict):
    conditions: list[str] = Field(default_factory=list)
    habits: list[str] = Field(default_factory=list)


class DemoUser(_Strict):
    id: str
    display_name: str
    city: str
    persona: Persona = Field(default_factory=Persona)
    rules: Rules


def load_users(path: str | Path) -> list[DemoUser]:
    """Read the seeded demo users. Our own config, so invalid rules raise (ValidationError) instead of falling back."""
    doc = yaml.safe_load(Path(path).read_text()) or {}
    return [DemoUser.model_validate(entry) for entry in doc.get("users", [])]


def load_rules(
    raw: dict | None, previous: Rules | None, default_station: int | None = None
) -> tuple[Rules, ReasonCode | None]:
    """Validate a user's rules. Missing fields take defaults; `location` falls back to `default_station`.

    Invalid rules return `previous` (or, with no previous version, the defaults) plus RULES_INVALID.
    Raises ValueError only when no station can be determined at all.
    """
    data = dict(raw or {})
    if "location" not in data and default_station is not None:
        data["location"] = {"station_id": default_station}
    try:
        return Rules.model_validate(data), None
    except ValidationError:
        if previous is not None:
            return previous, ReasonCode.RULES_INVALID
    station = default_station
    if station is None:
        try:
            station = Location.model_validate(data.get("location")).station_id
        except ValidationError:
            pass
    if station is None:
        raise ValueError("invalid rules with no previous version and no station to default to")
    return Rules(location=Location(station_id=station)), ReasonCode.RULES_INVALID
