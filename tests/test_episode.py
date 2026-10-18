"""D2 EPISODE (S-C §6): one bad period is one story."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from aqagent.decide.episode import EpisodeState, calm_run, step_episode, timeout_episode
from aqagent.decide.trigger import TriggerResult
from aqagent.types import Band, CandidateKind, EventKind, ReasonCode, StationScore

UTC = timezone.utc
H0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
FLOOR = Band.MODERATE


def score(band: Band | None, at: datetime = H0, nowcast: float = 40.0) -> StationScore:
    return StationScore(1, at, 0.0, 0.0, 0.0, 0.0, nowcast, band, Band.MODERATE)


def trig(label: EventKind | None = None, calm: bool = False) -> TriggerResult:
    return TriggerResult(label, frozenset({label}) if label else frozenset(), calm, (), {})


def active(**overrides) -> EpisodeState:
    base = EpisodeState(
        id=7,
        state="ACTIVE",
        opened_at=H0 - 5 * HOUR,
        closed_at=None,
        close_reason=None,
        kinds=frozenset({EventKind.climb}),
        peak_value=40.0,
        peak_band=Band.USG,
        last_notified_at=H0 - 5 * HOUR,
        last_notified_band=Band.USG,
        last_notified_kind=CandidateKind.opened,
        notifications_sent=1,
        last_hour=H0 - HOUR,
    )
    return replace(base, **overrides)


def closed(hours_ago: float, **overrides) -> EpisodeState:
    at = H0 - timedelta(hours=hours_ago)
    return active(state="CLOSED", closed_at=at, close_reason="calm", last_hour=at, **overrides)


def test_opens_when_event_and_moderate():
    ep, cand, reason = step_episode(None, None, trig(EventKind.climb), score(Band.USG, nowcast=45.0), 0, FLOOR, H0)
    assert (cand, reason) == (CandidateKind.opened, None)
    assert ep.state == "ACTIVE" and ep.id is None
    assert ep.opened_at == H0 and ep.closed_at is None
    assert ep.kinds == frozenset({EventKind.climb})
    assert (ep.peak_band, ep.peak_value) == (Band.USG, 45.0)
    assert ep.notifications_sent == 0 and ep.last_notified_band is None
    assert ep.last_hour == H0


def test_no_open_below_relevance():
    assert step_episode(None, None, trig(EventKind.climb), score(Band.GOOD), 0, FLOOR, H0) == (
        None,
        None,
        ReasonCode.NO_TRIGGER,
    )
    assert step_episode(None, None, trig(None), score(Band.USG), 0, FLOOR, H0) == (None, None, ReasonCode.NO_TRIGGER)


def test_escalation_candidate():
    ep, cand, reason = step_episode(active(), None, trig(), score(Band.UNHEALTHY, nowcast=80.0), 0, FLOOR, H0)
    assert (cand, reason) == (CandidateKind.escalated, None)
    assert ep.id == 7 and ep.state == "ACTIVE"
    assert (ep.peak_band, ep.peak_value) == (Band.UNHEALTHY, 80.0)
    ep, cand, reason = step_episode(active(), None, trig(EventKind.spike), score(Band.USG), 0, FLOOR, H0)
    assert (cand, reason) == (None, ReasonCode.EPISODE_CONTINUES)
    assert ep.kinds == frozenset({EventKind.climb, EventKind.spike})
    assert ep.last_hour == H0


def test_escalation_when_never_notified_compares_with_peak():
    never = active(last_notified_at=None, last_notified_band=None, last_notified_kind=None, notifications_sent=0)
    assert step_episode(never, None, trig(), score(Band.UNHEALTHY), 0, FLOOR, H0)[1] is CandidateKind.escalated
    assert step_episode(never, None, trig(), score(Band.USG), 0, FLOOR, H0)[1] is None


def test_qa_det_07_clearing_four_calm_hours():
    ep, cand, reason = step_episode(active(), None, trig(calm=True), score(Band.MODERATE), 3, FLOOR, H0)
    assert (ep.state, cand, reason) == ("RECOVERING", None, ReasonCode.EPISODE_CONTINUES)
    ep, cand, reason = step_episode(ep, None, trig(calm=True), score(Band.MODERATE, H0 + HOUR), 4, FLOOR, H0 + HOUR)
    assert (ep.state, cand, reason) == ("CLOSED", CandidateKind.cleared, None)
    assert (ep.closed_at, ep.close_reason, ep.id) == (H0 + HOUR, "calm", 7)


def test_recovering_returns_to_active_on_a_non_calm_hour():
    recovering = active(state="RECOVERING")
    ep, cand, reason = step_episode(recovering, None, trig(), score(Band.USG), 0, FLOOR, H0)
    assert (ep.state, cand, reason) == ("ACTIVE", None, ReasonCode.EPISODE_CONTINUES)


def test_qa_dedup_04_flap_guard():
    last = closed(4)
    ep, cand, reason = step_episode(None, last, trig(EventKind.spike), score(Band.USG), 0, FLOOR, H0)
    assert (ep.id, ep.state, cand, reason) == (7, "ACTIVE", None, ReasonCode.EPISODE_CONTINUES)
    assert (ep.closed_at, ep.close_reason) == (None, None)
    assert ep.notifications_sent == 1 and ep.last_notified_band is Band.USG
    assert EventKind.spike in ep.kinds
    ep, cand, reason = step_episode(None, last, trig(EventKind.spike), score(Band.UNHEALTHY), 0, FLOOR, H0)
    assert (ep.id, cand, reason) == (7, CandidateKind.escalated, None)
    # A closed episode passed as `prev` is treated the same way.
    assert step_episode(last, None, trig(EventKind.spike), score(Band.USG), 0, FLOOR, H0)[0].id == 7


def test_flap_guard_never_notified_episode_opens():
    last = closed(4, last_notified_at=None, last_notified_band=None, last_notified_kind=None, notifications_sent=0)
    ep, cand, _ = step_episode(None, last, trig(EventKind.climb), score(Band.USG), 0, FLOOR, H0)
    assert (ep.id, cand) == (7, CandidateKind.opened)


def test_after_flap_window_a_new_episode_opens():
    ep, cand, _ = step_episode(None, closed(7), trig(EventKind.climb), score(Band.USG), 0, FLOOR, H0)
    assert (ep.id, ep.opened_at, cand) == (None, H0, CandidateKind.opened)


def test_qa_dq_09_no_data_timeout():
    ep = active()
    newest = H0
    assert timeout_episode(ep, newest, H0 + 23 * HOUR) is ep
    out = timeout_episode(ep, newest, H0 + 24 * HOUR)
    assert (out.state, out.close_reason, out.closed_at, out.id) == ("CLOSED", "no_data_timeout", H0 + 24 * HOUR, 7)
    assert out.last_notified_band is ep.last_notified_band and out.notifications_sent == ep.notifications_sent
    assert timeout_episode(None, newest, H0 + 30 * HOUR) is None
    assert timeout_episode(out, newest, H0 + 30 * HOUR) is out
    # The quietly closed episode never produces a candidate afterwards: calm hours yield nothing.
    later = H0 + 25 * HOUR
    assert step_episode(out, None, trig(calm=True), score(Band.GOOD, later), 9, FLOOR, later) == (
        None,
        None,
        ReasonCode.NO_TRIGGER,
    )


def test_calm_run_counts_trailing_calm_hours():
    assert calm_run([]) == 0
    assert calm_run([trig(calm=True), trig(), trig(calm=True), trig(calm=True)]) == 2
    assert calm_run([trig(calm=True)] * 5) == 5
    assert calm_run([trig(calm=True), trig()]) == 0


def test_review_late_hour_does_not_rewind_episode():
    # Hours H..H+3 were evaluated; hour H arrives late (or revised). Nothing may move.
    ep = active(last_hour=H0 + 3 * HOUR)
    for hour in (H0, H0 + 3 * HOUR):
        for t, run in ((trig(calm=True), 4), (trig(EventKind.spike), 0)):
            out = step_episode(ep, None, t, score(Band.HAZARDOUS, hour), run, FLOOR, H0 + 4 * HOUR)
            assert out == (ep, None, ReasonCode.LATE_HOUR_SCORED)
            assert out[0] is ep
    # A late hour also can't reopen an episode that closed after it.
    last = closed(-3)  # closed at H+3
    assert step_episode(None, last, trig(EventKind.spike), score(Band.UNHEALTHY, H0 + HOUR), 0, FLOOR, H0 + 4 * HOUR) == (
        None,
        None,
        ReasonCode.LATE_HOUR_SCORED,
    )
    # The next new hour proceeds normally.
    nxt = H0 + 4 * HOUR
    ep2, cand, reason = step_episode(ep, None, trig(), score(Band.UNHEALTHY, nxt), 0, FLOOR, nxt)
    assert (cand, ep2.last_hour) == (CandidateKind.escalated, nxt)
