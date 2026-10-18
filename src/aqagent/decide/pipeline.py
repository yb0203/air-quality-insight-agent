"""The per-user decision pipeline (S-C §7): one evaluated hour, or one clock event, in, one Evaluation out.

Pure: no database, no clock. The runner gathers the context, calls these, and persists the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aqagent import params
from aqagent.decide import restraint
from aqagent.decide.episode import EpisodeState, calm_run, step_episode
from aqagent.decide.rules import Rules
from aqagent.decide.trigger import TriggerResult, triggers
from aqagent.types import (
    EVENT_PRECEDENCE, Band, Candidate, CandidateKind, EventKind, Outcome, ReasonCode, StationScore, TraceStep,
)

SENT_CODE = {
    CandidateKind.opened: ReasonCode.SENT_OPENED,
    CandidateKind.escalated: ReasonCode.SENT_ESCALATED,
    CandidateKind.cleared: ReasonCode.SENT_CLEARED,
    CandidateKind.check_in: ReasonCode.SENT_CHECK_IN,
    CandidateKind.released: ReasonCode.HELD_RELEASED,
}

REASON_TEXT = {
    ReasonCode.NO_DATA: "No fresh reading from the station.",
    ReasonCode.NO_BASELINE: "Not enough history yet to know what's normal here.",
    ReasonCode.DQ_INVALID: "The reading was invalid and was ignored.",
    ReasonCode.DQ_LOW_COVERAGE: "The hour was too incomplete to trust.",
    ReasonCode.DQ_STUCK: "The sensor looked stuck, so the reading was ignored.",
    ReasonCode.DQ_SUSPECT: "A one-hour sensor glitch was ignored.",
    ReasonCode.LATE_HOUR_SCORED: "A late reading was scored but didn't change what was already decided.",
    ReasonCode.NO_TRIGGER: "Nothing unusual.",
    ReasonCode.EPISODE_CONTINUES: "The same bad period is continuing; nothing new to say.",
    ReasonCode.NO_DATA_TIMEOUT: "The station went quiet for 24 hours, so the episode was closed without a message.",
    ReasonCode.BELOW_RELEVANCE: "Unusual for this place, but not at a level that affects health.",
    ReasonCode.DEDUP_SAME_BAND: "Already told you about this level; nothing new to say.",
    ReasonCode.RECOVERY_NOT_WORTH_SAYING: "It cleared up, but the bad period was too short or mild to announce.",
    ReasonCode.COOLDOWN: "Too soon after the last message about this.",
    ReasonCode.ARBITRATED_OUT: "Something more important was said this hour.",
    ReasonCode.DAILY_BUDGET: "Today's message budget is used up.",
    ReasonCode.QUIET_HOURS_HELD: "Held until quiet hours end.",
    ReasonCode.HELD_RELEASED: "Sent the message held overnight.",
    ReasonCode.HELD_EXPIRED: "The overnight message was no longer worth sending.",
    ReasonCode.CHECKIN_QUIET: "Check-in: nothing worse than usual today.",
    ReasonCode.RULES_INVALID: "Settings were invalid; the previous version was used.",
    ReasonCode.SENT_OPENED: "Sent: air quality turned bad.",
    ReasonCode.SENT_ESCALATED: "Sent: it got a full band worse.",
    ReasonCode.SENT_CLEARED: "Sent: back to normal after a bad period.",
    ReasonCode.SENT_CHECK_IN: "Sent at your check-in time.",
    ReasonCode.SENT_SEVERE_BYPASS: "Sent straight away: the air is severe.",
}


@dataclass(frozen=True)
class UserHourContext:
    user_id: str
    rules: Rules
    rules_version: int
    tz: ZoneInfo
    window: list[StationScore]  # ascending, at most 72h, the last one is the evaluated hour
    episode: EpisodeState | None
    last_closed: EpisodeState | None
    sent_today_nonsevere: int
    last_sent_at: datetime | None
    at: datetime


@dataclass(frozen=True)
class UserClockContext:
    user_id: str
    rules: Rules
    rules_version: int
    tz: ZoneInfo
    window: list[StationScore]  # the latest known scores, ascending
    episode: EpisodeState | None
    last_closed: EpisodeState | None
    sent_today_nonsevere: int
    last_sent_at: datetime | None
    at: datetime
    newest_reading_at: datetime | None


@dataclass(frozen=True)
class Evaluation:
    outcome: Outcome
    reason_code: ReasonCode
    trace: list[TraceStep]
    episode_after: EpisodeState | None
    candidate: Candidate | None = None
    absorbed: tuple[Candidate, ...] = ()
    trigger: TriggerResult | None = None
    score: StationScore | None = None
    bypassed: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return REASON_TEXT.get(self.reason_code, self.reason_code.value)


def evaluate_hour(ctx: UserHourContext) -> Evaluation:
    """Data path: run S2/U2 inputs -> D1 -> D2 -> D3..D8 -> A for one newly evaluated hour."""
    score = ctx.window[-1]
    trace: list[TraceStep] = []

    if score.excluded is not None or score.z is None:
        code = score.excluded or ReasonCode.NO_BASELINE
        trace.append(TraceStep("S2/U2", False, code, values={"period_end": score.period_end.isoformat()}))
        return Evaluation(Outcome.no_event, code, trace, ctx.episode, score=score)
    trace.append(TraceStep("S2/U2", True, values=_score_values(score)))

    results = triggers(ctx.window, ctx.rules.k, ctx.rules.alert_band)
    trig = results[-1]
    trace.append(TraceStep("D1", trig.label is not None, values={
        "label": trig.label.value if trig.label else None, "fired": sorted(k.value for k in trig.fired),
        "calm": trig.calm, "near_misses": list(trig.near_misses), "bars": trig.bars, "cusum": round(trig.cusum, 3),
        "k": ctx.rules.k}))

    run = calm_run(results)
    ep_after, kind, code = step_episode(ctx.episode, ctx.last_closed, trig, score, run,
                                        ctx.rules.relevance_floor, ctx.at)
    trace.append(TraceStep("D2", kind is not None, code, values={
        "state": ep_after.state if ep_after else None, "calm_run": run,
        "candidate": kind.value if kind else None, **_episode_values(ep_after, ctx.window, ctx.at)}))

    if kind is None:
        if code is ReasonCode.NO_TRIGGER and trig.label is not None and score.band is not None \
                and score.band < ctx.rules.relevance_floor:
            trace.append(TraceStep("D3", False, ReasonCode.BELOW_RELEVANCE,
                                   values={"band": score.band.slug, "relevance_floor": ctx.rules.relevance_floor.slug}))
            return Evaluation(Outcome.suppressed, ReasonCode.BELOW_RELEVANCE, trace, ep_after, trigger=trig, score=score)
        if code is ReasonCode.EPISODE_CONTINUES and trig.label is not None and ep_after is not None \
                and ep_after.last_notified_band is not None:
            trace.append(TraceStep("D3", False, ReasonCode.DEDUP_SAME_BAND, values={
                "band": _slug(score.band), "last_told": ep_after.last_notified_band.slug}))
            return Evaluation(Outcome.suppressed, ReasonCode.DEDUP_SAME_BAND, trace, ep_after, trigger=trig, score=score)
        return Evaluation(Outcome.no_event, code, trace, ep_after, trigger=trig, score=score)

    candidate = Candidate(kind, score.band, ep_after.id if ep_after else None,
                          _event_kind(trig, ep_after) if kind is not CandidateKind.cleared else None,
                          severe=bool(score.band is not None and score.band.is_severe))
    return _restrain(ctx, candidate, ep_after, trace, trig, score, is_check_in=False)


def evaluate_check_in(ctx: UserClockContext, held: list[Candidate]) -> Evaluation:
    """Clock path: the person's check-in time. Speaks only if today is shaping up worse than usual."""
    trace: list[TraceStep] = []
    score = ctx.window[-1] if ctx.window else None
    recent = [s for s in ctx.window if s.period_end > ctx.at - timedelta(hours=params.CHECKIN_WINDOW_HOURS)]
    bad = None
    if score is not None and score.band is not None:
        worse = (score.ewma is not None and score.ewma >= params.CHECKIN_MIN_EWMA) or \
            (score.typical_band is not None and score.band > score.typical_band)
        bad = score.band >= ctx.rules.relevance_floor and worse
    recent_gap = ctx.last_sent_at is not None and \
        ctx.at - ctx.last_sent_at < timedelta(hours=params.CHECKIN_MIN_GAP_HOURS)
    ep_open = ctx.episode if ctx.episode is not None and ctx.episode.is_open else None
    if ep_open is not None:
        trace.append(TraceStep("D2", True, values={"state": ep_open.state, **_episode_values(ep_open, ctx.window, ctx.at)}))
    trace.append(TraceStep("D8", bool(bad) and not recent_gap, None if bad and not recent_gap else ReasonCode.CHECKIN_QUIET,
                           values={"check_in": ctx.at.astimezone(ctx.tz).strftime("%H:%M"),
                                   "absorbed_held": len(held), "hours_considered": len(recent),
                                   "band": _slug(score.band) if score else None,
                                   "typical_band": _slug(score.typical_band) if score else None,
                                   "ewma": score.ewma if score else None, "recent_notice": recent_gap}))
    if not bad or recent_gap:
        return Evaluation(Outcome.no_event, ReasonCode.CHECKIN_QUIET, trace, ctx.episode, score=score)

    ep = ctx.episode if ctx.episode is not None and ctx.episode.is_open else None
    candidate = Candidate(CandidateKind.check_in, score.band, ep.id if ep else None,
                          _event_kind(None, ep), severe=score.band.is_severe)
    ev = _restrain(ctx, candidate, ep, trace, None, score, is_check_in=True, skip_story=True)
    return replace(ev, absorbed=tuple(held)) if ev.outcome is Outcome.sent else ev


def evaluate_release(ctx: UserClockContext, held: list[Candidate]) -> Evaluation:
    """Clock path: quiet hours ended. Everything held collapses into one message about the current state."""
    trace: list[TraceStep] = []
    score = ctx.window[-1] if ctx.window else None
    ep = ctx.episode if ctx.episode is not None and ctx.episode.is_open else None
    expired = (
        not held or ep is None or score is None or score.band is None
        or (ep.last_notified_band is not None and score.band <= ep.last_notified_band)
    )
    if ep is not None:
        trace.append(TraceStep("D2", True, values={"state": ep.state, **_episode_values(ep, ctx.window, ctx.at)}))
    trace.append(TraceStep("D8", not expired, ReasonCode.HELD_EXPIRED if expired else None, values={
        "held": len(held), "released": True, "episode_open": ep is not None,
        "band": _slug(score.band) if score else None}))
    if expired:
        return Evaluation(Outcome.suppressed, ReasonCode.HELD_EXPIRED, trace, ctx.episode, absorbed=tuple(held), score=score)
    candidate = Candidate(CandidateKind.released, score.band, ep.id, _event_kind(None, ep), severe=score.band.is_severe)
    ev = _restrain(ctx, candidate, ep, trace, None, score, is_check_in=False, skip_timing=True)
    return replace(ev, absorbed=tuple(held))


def _restrain(ctx, candidate: Candidate, ep: EpisodeState | None, trace: list[TraceStep], trig, score,
              *, is_check_in: bool, skip_story: bool = False, skip_timing: bool = False) -> Evaluation:
    def stop(outcome: Outcome, code: ReasonCode, episode=ep) -> Evaluation:
        return Evaluation(outcome, code, trace, episode, candidate, trigger=trig, score=score)

    bypassed = False
    if not skip_story:
        step = restraint.worth_it(candidate, ep, score)
        trace.append(step)
        if not step.passed:
            return stop(Outcome.suppressed, step.reason_code)
        step = restraint.pace(candidate, ep, ctx.at, ctx.rules.pace.base_gap_hours)
        trace.append(step)
        if not step.passed:
            return stop(Outcome.suppressed, step.reason_code)
        bypassed |= bool(step.values.get("severe_bypass"))

    candidate, outranked = restraint.arbitrate([candidate])  # D5 stub: one candidate per user per hour in v1
    trace.append(TraceStep("D5", True, values={"candidates": 1 + len(outranked), "kept": candidate.kind.value}))
    trace.append(restraint.respond(candidate))
    step = restraint.budget(ctx.sent_today_nonsevere, ctx.rules.budget.max_per_day, candidate.severe)
    trace.append(step)
    if not step.passed:
        return stop(Outcome.suppressed, step.reason_code)
    bypassed |= bool(step.values.get("severe_bypass"))

    if not skip_timing:
        step = restraint.timing(ctx.at.astimezone(ctx.tz), ctx.rules, candidate.band, is_check_in)
        trace.append(step)
        if not step.passed:
            return stop(Outcome.held, step.reason_code)
        bypassed |= bool(step.values.get("severe_bypass"))

    code = ReasonCode.SENT_SEVERE_BYPASS if bypassed and candidate.severe else SENT_CODE[candidate.kind]
    trace.append(TraceStep("A", True, code, values={"compose": candidate.kind.value}))
    told = _told(ep, candidate, ctx.at) if ep is not None else None
    return Evaluation(Outcome.sent, code, trace, told, candidate, trigger=trig, score=score, bypassed=bypassed)


def _told(ep: EpisodeState, candidate: Candidate, at: datetime) -> EpisodeState:
    return replace(ep, last_notified_at=at, last_notified_band=candidate.band, last_notified_kind=candidate.kind,
                   notifications_sent=ep.notifications_sent + 1)


def _event_kind(trig: TriggerResult | None, ep: EpisodeState | None) -> EventKind | None:
    if trig is not None and trig.label is not None:
        return trig.label
    kinds = ep.kinds if ep is not None else frozenset()
    return next((k for k in EVENT_PRECEDENCE if k in kinds), None)


def _episode_values(ep: EpisodeState | None, window: list[StationScore], at: datetime) -> dict:
    """Story facts for readers of the trace: when it started, how long, and its peak within the window."""
    if ep is None:
        return {}
    end = ep.closed_at or at
    inside = [s for s in window if s.nowcast is not None and s.period_end >= ep.opened_at - timedelta(hours=6)]
    peak = max(inside, key=lambda s: s.nowcast) if inside else None
    return {"started_at": ep.opened_at.isoformat(), "hours": round((end - ep.opened_at) / timedelta(hours=1), 1),
            "ended_at": ep.closed_at.isoformat() if ep.closed_at else None,
            "peak": {"pm25": round(peak.nowcast) if peak else ep.peak_value,
                     "at": peak.period_end.isoformat() if peak else None,
                     "band": ep.peak_band.slug if ep.peak_band else None}}


def _score_values(s: StationScore) -> dict:
    r = lambda v: round(v, 3) if isinstance(v, float) else v  # noqa: E731
    return {"period_end": s.period_end.isoformat(), "z": r(s.z), "ewma": r(s.ewma), "cusum": r(s.cusum),
            "slope_6h": r(s.slope_6h), "nowcast": r(s.nowcast), "band": _slug(s.band),
            "typical_band": _slug(s.typical_band)}


def _slug(band: Band | None) -> str | None:
    return band.slug if band is not None else None
