"""D3-D8 restraint and the per-user pipeline (S-C §7). Windows are StationScore lists built directly."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aqagent.decide.episode import EpisodeState
from aqagent.decide.pipeline import UserClockContext, UserHourContext, evaluate_check_in, evaluate_hour, evaluate_release
from aqagent.decide.restraint import arbitrate
from aqagent.decide.rules import Rules
from aqagent.types import Band, Candidate, CandidateKind, EventKind, Outcome, ReasonCode, StationScore

UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
HELSINKI = ZoneInfo("Europe/Helsinki")
HOUR = timedelta(hours=1)


def window(end: datetime, n=10, z=0.0, ewma=0.0, slope=0.0, band=Band.MODERATE, typical=Band.USG, nowcast=40.0):
    def col(v):
        return list(v) if isinstance(v, (list, tuple)) else [v] * n

    zs, es, ss, bs, ns = col(z), col(ewma), col(slope), col(band), col(nowcast)
    return [
        StationScore(1, end - (n - 1 - i) * HOUR, zs[i], es[i], 0.0, ss[i], ns[i], bs[i], typical)
        for i in range(n)
    ]


def climbing(end, band=Band.UNHEALTHY, typical=Band.USG, n=10):
    """A window whose last 3 hours are a confirmed climb."""
    return window(end, n=n, z=[0.5] * (n - 3) + [2.0] * 3, ewma=[0.5] * (n - 3) + [1.5] * 3, slope=0.03,
                  band=[Band.USG] * (n - 1) + [band], typical=typical, nowcast=[40.0] * (n - 1) + [80.0])


def calm(end, band=Band.MODERATE, typical=Band.USG, n=10):
    return window(end, n=n, z=0.0, ewma=0.1, slope=0.0, band=band, typical=typical, nowcast=20.0)


def rules(**kw):
    return Rules(location={"station_id": 1}, **kw)


def ctx(at, win, *, r=None, episode=None, last_closed=None, sent_today=0, last_sent_at=None, tz=IST):
    return UserHourContext(user_id="arjun", rules=r or rules(), rules_version=1, tz=tz, window=win,
                           episode=episode, last_closed=last_closed, sent_today_nonsevere=sent_today,
                           last_sent_at=last_sent_at, at=at)


def clock_ctx(at, win, *, r=None, episode=None, last_closed=None, sent_today=0, last_sent_at=None, tz=IST):
    return UserClockContext(user_id="arjun", rules=r or rules(), rules_version=1, tz=tz, window=win,
                            episode=episode, last_closed=last_closed, sent_today_nonsevere=sent_today,
                            last_sent_at=last_sent_at, at=at, newest_reading_at=win[-1].period_end if win else None)


def episode(opened_at, *, band=Band.USG, notified_band=None, notified_at=None, sent=0, peak=Band.USG, last_hour=None,
            state="ACTIVE", closed_at=None, peak_value=60.0):
    return EpisodeState(id=7, state=state, opened_at=opened_at, closed_at=closed_at, close_reason=None,
                        kinds=frozenset({EventKind.climb}), peak_value=peak_value, peak_band=peak,
                        last_notified_at=notified_at, last_notified_band=notified_band,
                        last_notified_kind=CandidateKind.opened if notified_band else None,
                        notifications_sent=sent, last_hour=last_hour)


# a daytime hour in Delhi: 14:20 IST
DAY = datetime(2026, 10, 18, 8, 50, tzinfo=UTC)


def test_opened_is_sent_in_daytime():
    ev = evaluate_hour(ctx(DAY, climbing(DAY)))
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.SENT_OPENED)
    assert ev.candidate.kind is CandidateKind.opened and ev.candidate.event_kind is EventKind.climb
    assert ev.episode_after.notifications_sent == 1 and ev.episode_after.last_notified_band is Band.UNHEALTHY


def test_qa_sens_04_relevance_floor():
    h = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    harmless = climbing(h, band=Band.GOOD, typical=Band.GOOD)
    ev = evaluate_hour(ctx(h, harmless, tz=HELSINKI))
    assert (ev.outcome, ev.reason_code) == (Outcome.suppressed, ReasonCode.BELOW_RELEVANCE)
    noticeable = climbing(h, band=Band.MODERATE, typical=Band.GOOD)
    assert evaluate_hour(ctx(h, noticeable, tz=HELSINKI)).outcome is Outcome.sent


def test_qa_dedup_01_six_bad_hours_one_notice():
    ep, sent, last_sent = None, [], None
    for i in range(6):
        at = DAY + i * HOUR
        ev = evaluate_hour(ctx(at, climbing(at), episode=ep, last_sent_at=last_sent))
        ep = ev.episode_after
        if ev.outcome is Outcome.sent:
            sent.append(at)
            last_sent = at
        else:
            assert ev.reason_code in (ReasonCode.DEDUP_SAME_BAND, ReasonCode.EPISODE_CONTINUES)
    assert len(sent) == 1


def test_qa_dedup_02_escalation_after_pace():
    told = DAY - 7 * HOUR
    ep = episode(told, notified_band=Band.USG, notified_at=told, sent=1, last_hour=DAY - HOUR)
    ev = evaluate_hour(ctx(DAY, climbing(DAY, band=Band.UNHEALTHY), episode=ep, last_sent_at=told))
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.SENT_ESCALATED)


def test_qa_dedup_03_same_band_quiet():
    told = DAY - 7 * HOUR
    ep = episode(told, notified_band=Band.UNHEALTHY, notified_at=told, sent=1, peak=Band.UNHEALTHY, last_hour=DAY - HOUR)
    ev = evaluate_hour(ctx(DAY, climbing(DAY, band=Band.UNHEALTHY), episode=ep, last_sent_at=told))
    assert (ev.outcome, ev.reason_code) == (Outcome.suppressed, ReasonCode.DEDUP_SAME_BAND)


def test_qa_dedup_05_pace_doubles():
    # 2nd notice in the episode needs 6h, the 3rd needs 12h
    for sent, gap_ok, gap_short in [(1, 6, 5), (2, 12, 11), (3, 24, 23)]:
        for gap, expect in [(gap_ok, Outcome.sent), (gap_short, Outcome.suppressed)]:
            told = DAY - gap * HOUR
            ep = episode(told - HOUR, notified_band=Band.USG, notified_at=told, sent=sent, last_hour=DAY - HOUR)
            ev = evaluate_hour(ctx(DAY, climbing(DAY, band=Band.UNHEALTHY), episode=ep, last_sent_at=told))
            assert ev.outcome is expect, (sent, gap)
            if expect is Outcome.suppressed:
                assert ev.reason_code is ReasonCode.COOLDOWN


def test_qa_dedup_06_budget():
    ev = evaluate_hour(ctx(DAY, climbing(DAY), sent_today=3))
    assert (ev.outcome, ev.reason_code) == (Outcome.suppressed, ReasonCode.DAILY_BUDGET)


def test_qa_dedup_11_budget_separate_from_pace():
    ev = evaluate_hour(ctx(DAY, climbing(DAY), sent_today=3, last_sent_at=DAY - 20 * HOUR))
    layers = {s.layer: s for s in ev.trace}
    assert layers["D4"].passed and not layers["D7"].passed
    assert ev.reason_code is ReasonCode.DAILY_BUDGET


def test_qa_dedup_07_severe_bypass():
    told = DAY - HOUR
    ep = episode(told - HOUR, notified_band=Band.UNHEALTHY, notified_at=told, sent=3, peak=Band.UNHEALTHY, last_hour=DAY - HOUR)
    ev = evaluate_hour(ctx(DAY, climbing(DAY, band=Band.VERY_UNHEALTHY), episode=ep, sent_today=3, last_sent_at=told))
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.SENT_SEVERE_BYPASS)


def _closing(hours_long: float, peak: Band, notified=True):
    opened = DAY - hours_long * HOUR
    ep = episode(opened, notified_band=Band.USG if notified else None, notified_at=opened if notified else None,
                 sent=1 if notified else 0, peak=peak, last_hour=DAY - HOUR, state="RECOVERING")
    return evaluate_hour(ctx(DAY, calm(DAY, band=Band.MODERATE), episode=ep, last_sent_at=opened if notified else None))


def test_qa_dedup_08_clear_worth_saying():
    short = _closing(5, Band.MODERATE)
    assert (short.outcome, short.reason_code) == (Outcome.suppressed, ReasonCode.RECOVERY_NOT_WORTH_SAYING)
    long_ = _closing(14, Band.MODERATE)
    assert (long_.outcome, long_.reason_code) == (Outcome.sent, ReasonCode.SENT_CLEARED)
    sharp = _closing(8, Band.UNHEALTHY)  # under 12h, but peaked at USG+ above the usual band (USG); 8h clears pace
    assert sharp.reason_code is ReasonCode.SENT_CLEARED
    never_told = _closing(14, Band.UNHEALTHY, notified=False)
    assert never_told.reason_code is ReasonCode.RECOVERY_NOT_WORTH_SAYING


def test_qa_dedup_09_arbitration():
    worse = Candidate(CandidateKind.escalated, Band.UNHEALTHY, 7, EventKind.climb)
    check = Candidate(CandidateKind.check_in, Band.UNHEALTHY)
    winner, losers = arbitrate([check, worse])
    assert winner is worse and losers == [check]


# 03:00 IST = 21:30 UTC the day before
NIGHT = datetime(2026, 10, 17, 21, 30, tzinfo=UTC)


def test_qa_rule_04_quiet_hours_hold():
    ev = evaluate_hour(ctx(NIGHT, climbing(NIGHT, band=Band.MODERATE, typical=Band.GOOD)))
    assert (ev.outcome, ev.reason_code) == (Outcome.held, ReasonCode.QUIET_HOURS_HELD)
    assert ev.episode_after.notifications_sent == 0  # nothing was actually told yet


def test_qa_rule_05_breakthrough():
    ev = evaluate_hour(ctx(NIGHT, climbing(NIGHT, band=Band.VERY_UNHEALTHY)))
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.SENT_SEVERE_BYPASS)


CHECKIN = datetime(2026, 10, 18, 1, 0, tzinfo=UTC)  # 06:30 IST


def test_qa_rule_08_check_in_speaks_only_when_worse():
    r = rules(check_in={"cron": "30 6 * * *"})
    bad = window(CHECKIN, n=10, ewma=1.4, band=Band.UNHEALTHY, typical=Band.USG, nowcast=90.0)
    ev = evaluate_check_in(clock_ctx(CHECKIN, bad, r=r), held=[])
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.SENT_CHECK_IN)
    ordinary = window(CHECKIN, n=10, ewma=0.2, band=Band.USG, typical=Band.USG, nowcast=45.0)
    ev = evaluate_check_in(clock_ctx(CHECKIN, ordinary, r=r), held=[])
    assert (ev.outcome, ev.reason_code) == (Outcome.no_event, ReasonCode.CHECKIN_QUIET)


def test_qa_rule_09_check_in_gap():
    bad = window(CHECKIN, n=10, ewma=1.4, band=Band.UNHEALTHY, typical=Band.USG, nowcast=90.0)
    ev = evaluate_check_in(clock_ctx(CHECKIN, bad, last_sent_at=CHECKIN - 4 * HOUR), held=[])
    assert ev.reason_code is ReasonCode.CHECKIN_QUIET


def test_qa_rule_14_check_in_wins_and_absorbs():
    held = [Candidate(CandidateKind.opened, Band.UNHEALTHY, 7, EventKind.climb)]
    bad = window(CHECKIN, n=10, ewma=1.4, band=Band.UNHEALTHY, typical=Band.USG, nowcast=90.0)
    ep = episode(CHECKIN - 6 * HOUR, last_hour=CHECKIN)
    ev = evaluate_check_in(clock_ctx(CHECKIN, bad, episode=ep), held=held)
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.SENT_CHECK_IN)  # inside quiet hours (until 07:00)
    assert ev.absorbed == tuple(held)
    assert ev.episode_after.notifications_sent == 1


QUIET_END = datetime(2026, 10, 18, 1, 30, tzinfo=UTC)  # 07:00 IST


def test_qa_rule_06_release_collapses():
    held = [Candidate(CandidateKind.opened, Band.USG, 7, EventKind.climb),
            Candidate(CandidateKind.escalated, Band.UNHEALTHY, 7, EventKind.climb),
            Candidate(CandidateKind.escalated, Band.UNHEALTHY, 7, EventKind.spike)]
    ep = episode(QUIET_END - 6 * HOUR, peak=Band.UNHEALTHY, last_hour=QUIET_END)
    ev = evaluate_release(clock_ctx(QUIET_END, climbing(QUIET_END), episode=ep), held=held)
    assert (ev.outcome, ev.reason_code) == (Outcome.sent, ReasonCode.HELD_RELEASED)
    assert ev.candidate.kind is CandidateKind.released and ev.absorbed == tuple(held)


def test_qa_rule_07_held_expired():
    held = [Candidate(CandidateKind.opened, Band.MODERATE, 7, EventKind.climb)]
    closed = episode(QUIET_END - 8 * HOUR, state="CLOSED", closed_at=QUIET_END - 2 * HOUR, last_hour=QUIET_END)
    ev = evaluate_release(clock_ctx(QUIET_END, calm(QUIET_END), episode=None, last_closed=closed), held=held)
    assert (ev.outcome, ev.reason_code) == (Outcome.suppressed, ReasonCode.HELD_EXPIRED)


def test_qa_sens_03_normal_for_delhi():
    """A week sitting at USG (normal for Delhi) never notifies; crossing into Very Unhealthy does, once."""
    ep, last_sent, sent = None, None, []
    start = DAY
    for i in range(7 * 24):
        at = start + i * HOUR
        w = window(at, n=10, z=0.3, ewma=0.3, slope=0.0, band=Band.USG, typical=Band.USG, nowcast=45.0)
        ev = evaluate_hour(ctx(at, w, episode=ep, last_sent_at=last_sent))
        ep = ev.episode_after
        if ev.outcome is Outcome.sent:
            sent.append(at)
    assert sent == []
    at = start + 7 * 24 * HOUR
    bands = [Band.USG] * 8 + [Band.VERY_UNHEALTHY] * 2  # the floor confirms on the 2nd hour above it
    w = window(at, n=10, z=0.3, ewma=0.3, band=bands, typical=Band.USG, nowcast=[45.0] * 8 + [150.0] * 2)
    ev = evaluate_hour(ctx(at, w, episode=ep, last_sent_at=last_sent))
    assert ev.outcome is Outcome.sent and ev.candidate.event_kind is EventKind.floor


def test_qa_rule_13_trace_order():
    order = ["S2/U2", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "A"]
    ev = evaluate_hour(ctx(DAY, climbing(DAY)))
    layers = [s.layer for s in ev.trace]
    assert layers == order[: len(layers)] and layers[-1] == "A"
    assert {"D5", "D6", "D7"} <= set(layers)


def test_qa_rule_10_local_time_dst():
    """Quiet hours follow local wall-clock time across Helsinki's DST change (2026-10-25)."""
    before = datetime(2026, 10, 24, 20, 30, tzinfo=UTC)  # 23:30 EEST -> quiet
    after = datetime(2026, 10, 25, 20, 30, tzinfo=UTC)  # 22:30 EET -> quiet
    morning = datetime(2026, 10, 26, 5, 30, tzinfo=UTC)  # 07:30 EET -> not quiet
    for at, held in [(before, True), (after, True), (morning, False)]:
        ev = evaluate_hour(ctx(at, climbing(at, band=Band.MODERATE, typical=Band.GOOD), tz=HELSINKI))
        assert (ev.outcome is Outcome.held) is held, at


def test_excluded_hour_is_no_event_with_its_reason():
    w = climbing(DAY)
    w[-1] = replace(w[-1], excluded=ReasonCode.DQ_SUSPECT, z=None, ewma=None)
    ev = evaluate_hour(ctx(DAY, w))
    assert (ev.outcome, ev.reason_code) == (Outcome.no_event, ReasonCode.DQ_SUSPECT)
