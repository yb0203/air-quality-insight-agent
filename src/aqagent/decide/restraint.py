"""D3-D8: the restraint layers (S-C §7.2). Each returns a TraceStep; none of them reads the clock."""
from __future__ import annotations

from datetime import datetime, timedelta

from aqagent import params
from aqagent.decide.episode import EpisodeState
from aqagent.decide.rules import Rules
from aqagent.types import Band, Candidate, CandidateKind, ReasonCode, StationScore, TraceStep

PRIORITY = (CandidateKind.escalated, CandidateKind.opened, CandidateKind.cleared, CandidateKind.check_in)


def worth_it(candidate: Candidate, episode: EpisodeState | None, score: StationScore) -> TraceStep:
    """D3: is there anything new in this story? (opened / escalated were already gated by D2)"""
    if candidate.kind is CandidateKind.cleared:
        if episode is None or episode.last_notified_band is None:
            return TraceStep("D3", False, ReasonCode.RECOVERY_NOT_WORTH_SAYING, values={"notified": False})
        hours = (episode.closed_at - episode.opened_at) / timedelta(hours=1) if episode.closed_at else 0.0
        peak, typical = episode.peak_band, score.typical_band
        sharp = peak is not None and peak >= Band.USG and (typical is None or peak > typical)
        ok = hours >= params.CLEAR_MIN_HOURS or sharp
        return TraceStep("D3", ok, None if ok else ReasonCode.RECOVERY_NOT_WORTH_SAYING,
                         values={"hours": round(hours, 1), "peak_band": peak.slug if peak else None,
                                 "typical_band": typical.slug if typical else None})
    return TraceStep("D3", True, values={"kind": candidate.kind.value, "band": _slug(candidate.band)})


def pace(candidate: Candidate, episode: EpisodeState | None, at: datetime, base_gap_h: int) -> TraceStep:
    """D4: too soon since this story last spoke? The gap doubles with each notice in the episode."""
    sent = episode.notifications_sent if episode else 0
    if sent == 0 or episode.last_notified_at is None:
        return TraceStep("D4", True, values={"notices_in_episode": sent})
    required = base_gap_h * 2 ** (sent - 1)
    elapsed = (at - episode.last_notified_at) / timedelta(hours=1)
    values = {"notices_in_episode": sent, "required_gap_h": required, "elapsed_h": round(elapsed, 2)}
    if elapsed >= required:
        return TraceStep("D4", True, values=values)
    if candidate.severe:
        return TraceStep("D4", True, values={**values, "severe_bypass": True})
    return TraceStep("D4", False, ReasonCode.COOLDOWN, values=values)


def arbitrate(candidates: list[Candidate]) -> tuple[Candidate, list[Candidate]]:
    """D5 (stub): keep one candidate per user per hour, by priority."""
    ranked = sorted(candidates, key=lambda c: PRIORITY.index(c.kind) if c.kind in PRIORITY else len(PRIORITY))
    return ranked[0], ranked[1:]


def respond(candidate: Candidate) -> TraceStep:
    """D6 (stub): the demo's only response is a notification."""
    return TraceStep("D6", True, values={"response": "notify"})


def budget(sent_nonsevere_today: int, max_per_day: int, severe: bool) -> TraceStep:
    """D7 (stub): a per-person attention budget across every story."""
    values = {"sent_today": sent_nonsevere_today, "max_per_day": max_per_day}
    if sent_nonsevere_today < max_per_day:
        return TraceStep("D7", True, values=values)
    if severe:
        return TraceStep("D7", True, values={**values, "severe_bypass": True})
    return TraceStep("D7", False, ReasonCode.DAILY_BUDGET, values=values)


def timing(at_local: datetime, rules: Rules, band: Band | None, is_check_in: bool) -> TraceStep:
    """D8: quiet hours hold messages unless the air is at the breakthrough band; a check-in always wins."""
    quiet = rules.in_quiet_hours(at_local)
    values = {"local_time": at_local.strftime("%H:%M"), "quiet_hours": quiet}
    if not quiet:
        return TraceStep("D8", True, values=values)
    if is_check_in:
        return TraceStep("D8", True, values={**values, "check_in_wins": True})
    if band is not None and band >= rules.quiet_hours.breakthrough_band:
        return TraceStep("D8", True, values={**values, "severe_bypass": True})
    until = rules.quiet_end_after(at_local)
    return TraceStep("D8", False, ReasonCode.QUIET_HOURS_HELD, values={**values, "held_until": until.isoformat()})


def _slug(band: Band | None) -> str | None:
    return band.slug if band is not None else None
