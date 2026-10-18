"""Task 12: the runner (data run + clock tick) end to end over an in-memory database."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aqagent import db, repo
from aqagent.clock import FixedClock
from aqagent.decide.episode import EpisodeState
from aqagent.runner import clock_tick, data_run, load_episodes, save_episode
from aqagent.types import Band, CandidateKind, EventKind, Reading

UTC = timezone.utc
HOUR = timedelta(hours=1)
LAG = timedelta(minutes=50)  # readings for hour H (ending :30 UTC in India) arrive at H+50min, i.e. :20 UTC
T0 = datetime(2026, 10, 10, 0, 30, tzinfo=UTC)  # first period_end (06:00 IST)
SENSOR, PM10, STATION = 15289075, 99, 4712609


def base_value(i: int) -> float:
    return 40.0 + 6.0 * math.sin(i / 3.0) + 2.0 * math.cos(i / 1.7)


def reading(i: int, value: float | None = None, sensor=SENSOR) -> Reading:
    end = T0 + i * HOUR
    return Reading(sensor, end, end - HOUR, base_value(i) if value is None else value, 100.0)


@pytest.fixture
def conn():
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    with engine.begin() as c:
        repo.upsert_station(c, id=STATION, city="Delhi", name="Air Check", provider="AirGradient",
                            timezone="Asia/Kolkata", is_reference=False)
        repo.upsert_sensor(c, id=SENSOR, station_id=STATION, parameter="pm25", units="µg/m³")
        repo.upsert_sensor(c, id=PM10, station_id=STATION, parameter="pm10", units="µg/m³")
        for uid, name, rules in [
            ("arjun", "Arjun", {"location": {"station_id": STATION}, "check_in": {"cron": "30 6 * * *"}}),
            ("meera", "Meera", {"location": {"station_id": STATION}, "sensitivity": "high"}),
        ]:
            repo.upsert_user(c, id=uid, display_name=name, station_id=STATION, city="Delhi",
                             persona={"conditions": [], "habits": ["morning run 06:30"] if uid == "arjun" else []})
            repo.save_rules(c, uid, rules, "user", T0)
    with engine.begin() as c:
        yield c


def feed(conn, readings: list[Reading], arrive: datetime, clock: FixedClock, llm=None):
    """Ingest `readings` as arriving at `arrive`, then run the data path at that time."""
    clock.set(arrive)
    new, revised = repo.upsert_readings_detailed(conn, readings, arrive, None)
    changed = {}
    for r in readings:
        if r.period_end in set(new) | set(revised):
            changed.setdefault(r.sensor_id, []).append(r.period_end)
    return data_run(conn, changed, clock, llm)


def warm_up(conn, clock, hours=96):
    """Backfill `hours` of normal data in one go (as an initial backfill would), then return the next index."""
    feed(conn, [reading(i) for i in range(hours)], T0 + hours * HOUR + LAG, clock)
    return hours


def decisions(conn, **where):
    q = sa.select(db.decisions).order_by(db.decisions.c.id)
    for k, v in where.items():
        q = q.where(db.decisions.c[k] == v)
    return conn.execute(q).mappings().all()


def test_episode_round_trip(conn):
    ep = EpisodeState(id=None, state="ACTIVE", opened_at=T0, closed_at=None, close_reason=None,
                      kinds=frozenset({EventKind.climb, EventKind.spike}), peak_value=88.0, peak_band=Band.UNHEALTHY,
                      last_notified_at=T0, last_notified_band=Band.USG, last_notified_kind=CandidateKind.opened,
                      notifications_sent=1, last_hour=T0)
    eid = save_episode(conn, "arjun", SENSOR, ep)
    open_, closed = load_episodes(conn, "arjun", SENSOR)
    assert closed is None and open_.id == eid
    assert open_.kinds == ep.kinds and open_.peak_band is Band.UNHEALTHY and open_.last_notified_kind is CandidateKind.opened


def test_qa_obs_01_row_per_user_hour(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    before = len(decisions(conn))
    for i in range(n, n + 24):
        feed(conn, [reading(i)], T0 + i * HOUR + LAG, clock)
    rows = decisions(conn)[before:]
    assert len(rows) == 24 * 2  # 24 hours x 2 users
    assert {r["trigger"] for r in rows} == {"data"}


def test_qa_ing_05_outage_hours_all_evaluated_in_order(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    before = len(decisions(conn, user_id="arjun"))
    feed(conn, [reading(i) for i in range(n, n + 5)], T0 + (n + 5) * HOUR + LAG, clock)  # 5 hours at once
    rows = decisions(conn, user_id="arjun")[before:]
    assert [r["period_end"] for r in rows] == [T0 + i * HOUR for i in range(n, n + 5)]


def test_review_late_hour_does_not_rewind_episode(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    feed(conn, [reading(i) for i in range(n + 1, n + 4)], T0 + (n + 4) * HOUR + LAG, clock)  # hour n missing
    ep_before = load_episodes(conn, "arjun", SENSOR)
    feed(conn, [reading(n, 400.0)], T0 + (n + 5) * HOUR + LAG, clock)  # hour n arrives late, and huge
    last = decisions(conn, user_id="arjun")[-1]
    assert last["period_end"] == T0 + n * HOUR and last["reason_code"] == "LATE_HOUR_SCORED"
    assert load_episodes(conn, "arjun", SENSOR) == ep_before
    assert conn.execute(sa.select(sa.func.count()).select_from(db.notifications)).scalar() == 0


def climb_values(n0: int, hours: int) -> list[Reading]:
    return [reading(n0 + j, base_value(n0 + j) * (1.25 ** (j + 1))) for j in range(hours)]


def test_climb_tells_once_then_once_more_when_severe(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)  # n=96 -> hour n ends 06:30 UTC = 12:00 IST (daytime)
    for j, r in enumerate(climb_values(n, 8)):
        feed(conn, [r], r.period_end + LAG, clock)
    notes = conn.execute(sa.select(db.notifications).where(db.notifications.c.user_id == "arjun")
                         .order_by(db.notifications.c.id)).mappings().all()
    # a 6x climb: told once when it turns unhealthy, once more (severe, skipping pace) at very unhealthy
    assert [n["kind"] for n in notes] == ["opened", "escalated"]
    assert notes[1]["context_facts"]["now"]["band"] == "very_unhealthy"
    for n in notes:
        assert len(n["body"]) <= 220 and n["next_action"].lower() in n["body"].lower()
        assert n["generator"] == "template" and n["delivered_at"] is not None


def test_qa_obs_02_suppressed_and_held_are_complete(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    for r in climb_values(n, 8):
        feed(conn, [r], r.period_end + LAG, clock)
    rows = [r for r in decisions(conn) if r["outcome"] in ("suppressed", "held")]
    assert rows, "expected some suppressed decisions after the first notice"
    for r in rows:
        assert r["reason_code"] and r["reason"] and r["trace"] and r["score_ids"]


def test_qa_clk_01_no_data_decisions(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    last_arrival = T0 + (n - 1) * HOUR + LAG
    for h in range(1, 6):
        clock.set(last_arrival + h * HOUR)
        clock_tick(conn, clock, None, "hourly")
    rows = decisions(conn, user_id="arjun", trigger="clock")
    codes = [r["reason_code"] for r in rows]
    assert codes and set(codes) == {"NO_DATA"}
    assert len(codes) == 3  # only ticks where the newest reading is > 3h old: age = 50min + h hours, so h = 3, 4, 5


def test_qa_dq_09_no_data_timeout_closes_quietly(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    for r in climb_values(n, 6):
        feed(conn, [r], r.period_end + LAG, clock)
    assert load_episodes(conn, "arjun", SENSOR)[0] is not None
    sent_before = conn.execute(sa.select(sa.func.count()).select_from(db.notifications)).scalar()
    silent_from = T0 + (n + 5) * HOUR + LAG
    for h in range(1, 26):
        clock.set(silent_from + h * HOUR)
        clock_tick(conn, clock, None, "hourly")
    open_, closed = load_episodes(conn, "arjun", SENSOR)
    assert open_ is None and closed.close_reason == "no_data_timeout"
    assert "NO_DATA_TIMEOUT" in [r["reason_code"] for r in decisions(conn, user_id="arjun")]
    assert conn.execute(sa.select(sa.func.count()).select_from(db.notifications)).scalar() == sent_before


def test_qa_clk_02_held_released_at_quiet_end_without_new_data(conn):
    clock = FixedClock(T0)
    # hour index 112 ends 16:30 UTC = 22:00 IST; climb from there into quiet hours
    n = warm_up(conn, clock, hours=113)
    for r in climb_values(n, 6):
        feed(conn, [r], r.period_end + LAG, clock)
    held = [r for r in decisions(conn, user_id="meera") if r["outcome"] == "held"]
    assert held, "the night climb should be held for Meera (no check-in)"
    quiet_end = datetime(2026, 10, 15, 1, 30, tzinfo=UTC)  # 07:00 IST
    clock.set(quiet_end)
    clock_tick(conn, clock, None, "quiet_end", ["meera"])
    rel = decisions(conn, user_id="meera", trigger="clock")[-1]
    assert rel["reason_code"] in ("HELD_RELEASED", "HELD_EXPIRED")
    assert conn.execute(sa.select(sa.func.count()).select_from(db.held_notices)
                        .where(db.held_notices.c.released_decision_id.is_(None))
                        .where(db.held_notices.c.user_id == "meera")).scalar() == 0


def test_qa_dedup_10_restart_safe(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    vals = climb_values(n, 8)
    for r in vals[:4]:
        feed(conn, [r], r.period_end + LAG, clock)
    # "restart": nothing is held in memory, so just keep feeding against the same DB
    for r in vals[4:]:
        feed(conn, [r], r.period_end + LAG, clock)
    opened = conn.execute(sa.select(db.notifications).where(db.notifications.c.user_id == "arjun")
                          .where(db.notifications.c.kind == "opened")).all()
    assert len(opened) == 1


def test_qa_sens_05_scores_independent_of_users(conn):
    """Stored station scores equal the pure score with no user input at all, whoever is subscribed."""
    from zoneinfo import ZoneInfo

    from aqagent.understand.score import score_hours

    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    repo.upsert_user(conn, id="zed", display_name="Zed", station_id=STATION, city="Delhi", persona={})
    repo.save_rules(conn, "zed", {"location": {"station_id": STATION}, "sensitivity": "low"}, "user", T0)
    at = T0 + n * HOUR + LAG
    feed(conn, [reading(n)], at, clock)
    stored = repo.scores_window(conn, SENSOR, T0 + n * HOUR, hours=1)
    known = repo.readings_as_of(conn, SENSOR, T0 - 30 * HOUR, T0 + n * HOUR, at)
    pure = score_hours(known, ZoneInfo("Asia/Kolkata"), [T0 + n * HOUR], at, sensor_id=SENSOR)
    assert stored == pure


def test_qa_rule_12_pollutant_filter(conn):
    clock = FixedClock(T0)
    n = warm_up(conn, clock)
    before = len(decisions(conn))
    feed(conn, [reading(n, 500.0, sensor=PM10)], T0 + n * HOUR + LAG, clock)
    assert len(decisions(conn)) == before  # pm10 hours never reach pm25 users
