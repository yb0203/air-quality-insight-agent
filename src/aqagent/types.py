"""Shared value types. Every layer speaks in these."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum


class Band(IntEnum):
    """US EPA 2024 PM2.5 categories, ordered from best to worst."""

    GOOD = 0
    MODERATE = 1
    USG = 2
    UNHEALTHY = 3
    VERY_UNHEALTHY = 4
    HAZARDOUS = 5

    @property
    def slug(self) -> str:
        return self.name.lower()

    @property
    def is_severe(self) -> bool:
        return self >= Band.VERY_UNHEALTHY

    @property
    def label(self) -> str:
        return {
            Band.GOOD: "good",
            Band.MODERATE: "moderate",
            Band.USG: "unhealthy for sensitive groups",
            Band.UNHEALTHY: "unhealthy",
            Band.VERY_UNHEALTHY: "very unhealthy",
            Band.HAZARDOUS: "hazardous",
        }[self]

    @classmethod
    def parse(cls, value: str | Band) -> Band:
        if isinstance(value, Band):
            return value
        return cls[value.strip().upper()]


class EventKind(StrEnum):
    spike = "spike"
    climb = "climb"
    elevated = "elevated"
    floor = "floor"


EVENT_PRECEDENCE = (EventKind.spike, EventKind.climb, EventKind.elevated, EventKind.floor)


class CandidateKind(StrEnum):
    opened = "opened"
    escalated = "escalated"
    cleared = "cleared"
    check_in = "check_in"
    released = "released"


class Outcome(StrEnum):
    sent = "sent"
    held = "held"
    suppressed = "suppressed"
    no_event = "no_event"


class ReasonCode(StrEnum):
    NO_DATA = "NO_DATA"
    NO_BASELINE = "NO_BASELINE"
    DQ_INVALID = "DQ_INVALID"
    DQ_LOW_COVERAGE = "DQ_LOW_COVERAGE"
    DQ_STUCK = "DQ_STUCK"
    DQ_SUSPECT = "DQ_SUSPECT"
    LATE_HOUR_SCORED = "LATE_HOUR_SCORED"
    NO_TRIGGER = "NO_TRIGGER"
    EPISODE_CONTINUES = "EPISODE_CONTINUES"
    NO_DATA_TIMEOUT = "NO_DATA_TIMEOUT"
    BELOW_RELEVANCE = "BELOW_RELEVANCE"
    DEDUP_SAME_BAND = "DEDUP_SAME_BAND"
    RECOVERY_NOT_WORTH_SAYING = "RECOVERY_NOT_WORTH_SAYING"
    COOLDOWN = "COOLDOWN"
    ARBITRATED_OUT = "ARBITRATED_OUT"
    DAILY_BUDGET = "DAILY_BUDGET"
    QUIET_HOURS_HELD = "QUIET_HOURS_HELD"
    HELD_RELEASED = "HELD_RELEASED"
    HELD_EXPIRED = "HELD_EXPIRED"
    CHECKIN_QUIET = "CHECKIN_QUIET"
    RULES_INVALID = "RULES_INVALID"
    SENT_OPENED = "SENT_OPENED"
    SENT_ESCALATED = "SENT_ESCALATED"
    SENT_CLEARED = "SENT_CLEARED"
    SENT_CHECK_IN = "SENT_CHECK_IN"
    SENT_SEVERE_BYPASS = "SENT_SEVERE_BYPASS"


@dataclass(frozen=True)
class Reading:
    sensor_id: int
    period_end: datetime
    period_start: datetime
    value: float | None
    coverage_pct: float | None = None


@dataclass(frozen=True)
class TraceStep:
    layer: str
    passed: bool
    reason_code: ReasonCode | None = None
    inputs: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "layer": self.layer,
            "passed": self.passed,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "inputs": self.inputs,
            "values": self.values,
        }


@dataclass(frozen=True)
class CheckedReading:
    """S2 output: a reading plus why it was excluded (None = usable). `provisional` = newest hour, glitch check pending."""

    reading: Reading
    excluded: ReasonCode | None = None
    provisional: bool = False


@dataclass(frozen=True)
class StationScore:
    """U2 output, shared by every user on the station. Contains no user parameters (FR-SENS-4)."""

    sensor_id: int
    period_end: datetime
    z: float | None
    ewma: float | None
    cusum: float | None
    slope_6h: float | None
    nowcast: float | None
    band: Band | None
    typical_band: Band | None
    excluded: ReasonCode | None = None
    gap_break: bool = False
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    """Something the decision layers might say (D2 output, D3-D8 input)."""

    kind: CandidateKind
    band: Band | None
    episode_id: int | None = None
    event_kind: EventKind | None = None
    severe: bool = False
