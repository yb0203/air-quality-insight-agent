"""D2 EPISODE (S-C §6): one bad period is one story, per user and station.

NORMAL -> ACTIVE when a trigger fires and the band is at least the user's relevance floor.
ACTIVE -> RECOVERING on a calm hour; RECOVERING -> ACTIVE on a trigger or a non-calm hour.
-> CLOSED after CALM_HOURS consecutive calm hours (candidate `cleared`).
A trigger within FLAP_HOURS of a close reopens the same episode (flap guard), with no `opened`.
Silence: NO_DATA for NO_DATA_TIMEOUT_HOURS closes it quietly, never with a candidate.

Pure functions: every step returns a new EpisodeState. Persistence (ids, rows) is the caller's job.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from aqagent import params
from aqagent.decide.trigger import TriggerResult
from aqagent.types import Band, CandidateKind, EventKind, ReasonCode, StationScore

CLOSE_CALM = "calm"
CLOSE_NO_DATA = "no_data_timeout"


@dataclass(frozen=True)
class EpisodeState:
    """Mirrors the `episodes` row (S-A §5), plus `last_hour`: the newest hour this episode has processed."""

    id: int | None
    state: Literal["ACTIVE", "RECOVERING", "CLOSED"]
    opened_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    kinds: frozenset[EventKind]
    peak_value: float | None
    peak_band: Band | None
    last_notified_at: datetime | None
    last_notified_band: Band | None
    last_notified_kind: CandidateKind | None
    notifications_sent: int
    last_hour: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.state != "CLOSED"


def calm_run(results: list[TriggerResult]) -> int:
    """The number of trailing consecutive calm hours."""
    n = 0
    for r in reversed(results):
        if not r.calm:
            break
        n += 1
    return n


def _max(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _absorb(ep: EpisodeState, trig: TriggerResult, score: StationScore) -> EpisodeState:
    """Fold this hour into the episode: kinds seen, peak, and the newest processed hour."""
    return replace(
        ep,
        kinds=ep.kinds | trig.fired,
        peak_value=_max(ep.peak_value, score.nowcast),
        peak_band=_max(ep.peak_band, score.band),
        last_hour=score.period_end,
    )


def _above(band: Band | None, reference: Band | None) -> bool:
    return band is not None and reference is not None and band >= reference + 1


def step_episode(
    prev: EpisodeState | None,
    last_closed: EpisodeState | None,
    trig: TriggerResult,
    score: StationScore,
    calm_run: int,
    relevance_floor: Band,
    at: datetime,
) -> tuple[EpisodeState | None, CandidateKind | None, ReasonCode | None]:
    """Advance the episode by one evaluated hour (`score.period_end`).

    Returns (episode after, candidate, reason). `reason` is None exactly when there is a candidate.
    `at` stamps opened_at / closed_at and measures the flap window. An hour at or before the newest
    hour already processed (`last_hour`) changes nothing: (prev, None, LATE_HOUR_SCORED).
    """
    hour = score.period_end
    given = prev
    closed = [e for e in (prev, last_closed) if e is not None and not e.is_open and e.closed_at is not None]
    last_closed = max(closed, key=lambda e: e.closed_at) if closed else None
    prev = prev if prev is not None and prev.is_open else None

    seen = [e.last_hour for e in (prev, last_closed) if e is not None and e.last_hour is not None]
    if seen and hour <= max(seen):
        return given, None, ReasonCode.LATE_HOUR_SCORED

    if prev is not None:
        ep = _absorb(prev, trig, score)
        if trig.calm and calm_run >= params.CALM_HOURS:
            return replace(ep, state="CLOSED", closed_at=at, close_reason=CLOSE_CALM), CandidateKind.cleared, None
        if trig.calm:
            return replace(ep, state="RECOVERING"), None, ReasonCode.EPISODE_CONTINUES
        ep = replace(ep, state="ACTIVE")
        # Never notified (held, suppressed): measure escalation from the worst band seen so far.
        reference = prev.last_notified_band if prev.last_notified_band is not None else prev.peak_band
        if _above(score.band, reference):
            return ep, CandidateKind.escalated, None
        return ep, None, ReasonCode.EPISODE_CONTINUES

    if trig.label is None or score.band is None or score.band < relevance_floor:
        return None, None, ReasonCode.NO_TRIGGER

    flap = timedelta(hours=params.FLAP_HOURS)
    if last_closed is not None and at - last_closed.closed_at < flap:
        ep = _absorb(replace(last_closed, state="ACTIVE", closed_at=None, close_reason=None), trig, score)
        if last_closed.last_notified_band is None:
            return ep, CandidateKind.opened, None
        if _above(score.band, last_closed.last_notified_band):
            return ep, CandidateKind.escalated, None
        return ep, None, ReasonCode.EPISODE_CONTINUES

    ep = EpisodeState(
        id=None,
        state="ACTIVE",
        opened_at=at,
        closed_at=None,
        close_reason=None,
        kinds=trig.fired,
        peak_value=score.nowcast,
        peak_band=score.band,
        last_notified_at=None,
        last_notified_band=None,
        last_notified_kind=None,
        notifications_sent=0,
        last_hour=hour,
    )
    return ep, CandidateKind.opened, None


def timeout_episode(prev: EpisodeState | None, newest_reading_at: datetime, at: datetime) -> EpisodeState | None:
    """Clock tick: close an open episode quietly after NO_DATA_TIMEOUT_HOURS of silence. Never a candidate."""
    if prev is None or not prev.is_open:
        return prev
    if at - newest_reading_at >= timedelta(hours=params.NO_DATA_TIMEOUT_HOURS):
        return replace(prev, state="CLOSED", closed_at=at, close_reason=CLOSE_NO_DATA)
    return prev
