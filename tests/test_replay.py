"""Task 13: replay the shipped 90-day sample through the real runner, as known at each moment."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

from aqagent import db
from aqagent.replay.harness import replay, report, schedule
from aqagent.replay.labels import all_moments
from aqagent.replay.load import load_sample
from aqagent.seed import seed_users

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data/samples/openaq_pm25_hourly_90d.csv"
STATIONS = ROOT / "data/samples/stations.json"
LABELS = ROOT / "data/labels.yaml"
START = datetime(2026, 7, 21, 0, 0, tzinfo=UTC)
END = datetime(2026, 10, 18, 3, 0, tzinfo=UTC)


def fresh(location_ids=None, extra_users=()):
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    conn = engine.connect()
    with conn.begin():
        load_sample(conn, CSV, STATIONS, lag_hours=1.5, location_ids=location_ids)
        seed_users(conn, START)
        for uid, station, rules in extra_users:
            from aqagent import repo
            repo.upsert_user(conn, id=uid, display_name=uid.title(), station_id=station, persona={}, city="Fixture")
            repo.save_rules(conn, uid, rules, "user", START)
    return conn


@pytest.fixture(scope="module")
def full():
    """One full 90-day replay shared by the volume/catch tests (slow, done once)."""
    conn = fresh()
    with conn.begin():
        summary = replay(conn, START, END, "full")
    return conn, summary


def test_schedule_has_hourly_ticks_and_user_events():
    conn = fresh(location_ids={4712609})
    ev = schedule(conn, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC))
    kinds = [k for _t, k, _u in ev]
    assert kinds.count("hourly") == 24
    assert ("check_in", ["arjun"]) in [(k, u) for _t, k, u in ev]
    assert any(k == "quiet_end" for k in kinds)
    times = [t for t, _k, _u in ev]
    assert times == sorted(times)


def test_qa_eval_01_runs_without_key(monkeypatch):
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    conn = fresh(location_ids={4588, 4712609})
    with conn.begin():
        s = replay(conn, datetime(2026, 8, 20, tzinfo=UTC), datetime(2026, 8, 27, tzinfo=UTC), "week")
    assert s.ticks == 7 * 24 and s.decisions > 0


def test_qa_obs_06_replay_tagged():
    conn = fresh(location_ids={4588})
    with conn.begin():
        replay(conn, datetime(2026, 8, 20, tzinfo=UTC), datetime(2026, 8, 22, tzinfo=UTC), "tag")
    runs = {r for (r,) in conn.execute(sa.select(db.decisions.c.replay_run).distinct())}
    assert runs == {"tag"}


def test_qa_eval_04_helsinki_smoke_caught():
    conn = fresh(location_ids={4588})
    with conn.begin():
        replay(conn, datetime(2026, 8, 10, tzinfo=UTC), datetime(2026, 8, 25, tzinfo=UTC), "smoke")
    d = db.decisions
    hits = conn.execute(sa.select(d.c.period_end, d.c.outcome).where(
        d.c.user_id == "aino", d.c.outcome.in_(["sent", "held"]),
        d.c.period_end >= datetime(2026, 8, 23, 23, tzinfo=UTC),
        d.c.period_end <= datetime(2026, 8, 24, 11, tzinfo=UTC))).all()
    assert hits, "Aino should hear about the 24 Aug smoke within 6 hours of its onset"


def test_qa_eval_03_glitch_fixture_silent():
    rules = {"location": {"station_id": 8039}, "sensitivity": "high"}
    conn = fresh(location_ids={8039}, extra_users=[("mumbai_tester", 8039, rules)])
    with conn.begin():
        replay(conn, datetime(2026, 8, 17, tzinfo=UTC), datetime(2026, 10, 18, tzinfo=UTC), "glitch")
    d = db.decisions
    rows = conn.execute(sa.select(d.c.reason_code, d.c.outcome).where(d.c.user_id == "mumbai_tester")).all()
    assert any(code == "DQ_SUSPECT" for code, _ in rows)
    sent_on_glitch = conn.execute(sa.select(sa.func.count()).select_from(d).where(
        d.c.user_id == "mumbai_tester", d.c.outcome == "sent", d.c.reason_code == "DQ_SUSPECT")).scalar()
    assert sent_on_glitch == 0
    moments = all_moments(conn, LABELS)
    rep = report(conn, "glitch", moments, datetime(2026, 8, 17, tzinfo=UTC), datetime(2026, 10, 18, tzinfo=UTC))
    assert rep["mumbai_tester"]["glitch_notices"] == 0


def test_qa_eval_02_report_fields(full):
    conn, _ = full
    rep = report(conn, "full", all_moments(conn, LABELS), START, END)
    assert set(rep) >= {"arjun", "meera", "priya", "omar", "maya", "aino"}
    for row in rep.values():
        assert {"caught", "missed", "false_alarms", "notices_per_week", "median_time_to_notify_h",
                "near_misses_by_missed"} <= set(row)


def test_qa_eval_06_volume_guard(full):
    conn, _ = full
    rep = report(conn, "full", all_moments(conn, LABELS), START, END)
    for uid in ("arjun", "priya", "maya"):  # the default-sensitivity personas
        assert rep[uid]["event_notices_per_week"] <= 4, (uid, rep[uid])  # opened/escalated/cleared/released
        assert rep[uid]["notices_per_week"] <= 5, (uid, rep[uid])  # including the morning check-ins


def test_qa_det_10_same_value_differs_by_city():
    """Three hours at 25 µg/m³ are a spike in Helsinki and an ordinary afternoon in Delhi."""
    from aqagent.understand.score import score_hours
    from zoneinfo import ZoneInfo
    from aqagent import repo

    conn = fresh(location_ids={4588, 4712609})
    at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    for sensor, tz in [(11382, "Europe/Helsinki"), (15289075, "Asia/Kolkata")]:
        from aqagent.decide.trigger import triggers
        from aqagent.types import Band, EventKind

        known = repo.readings_as_of(conn, sensor, at - timedelta(days=15), at, at)
        R = type(known[-1])
        spiked = known[:-3] + [R(sensor, r.period_end, r.period_start, 25.0, 100.0) for r in known[-3:]]
        hours = [r.period_end for r in spiked[-72:]]
        scores = score_hours(spiked, ZoneInfo(tz), hours, at)
        fired = triggers(scores, 1.0, Band.VERY_UNHEALTHY)[-1].fired
        if sensor == 11382:
            assert EventKind.spike in fired
        else:
            assert not fired and scores[-1].z < 0  # 25 is below a normal Delhi hour


def test_qa_det_12_live_equals_replay():
    """Hour-by-hour 'live' runs and one replay over the same as-known data decide the same."""
    from aqagent.clock import FixedClock
    from aqagent.runner import clock_tick, data_run
    from aqagent.replay.harness import _arrived

    start, end = datetime(2026, 8, 22, tzinfo=UTC), datetime(2026, 8, 25, tzinfo=UTC)
    a = fresh(location_ids={4588})
    with a.begin():
        replay(a, start, end, "r")
    b = fresh(location_ids={4588})
    with b.begin():
        clock, last = FixedClock(start), start - timedelta(days=120)
        for t, kind, users in schedule(b, start, end):
            clock.set(t)
            if kind == "hourly":
                data_run(b, _arrived(b, last, t), clock, None, replay_run="r")
                last = t
            clock_tick(b, clock, None, kind, users, replay_run="r")
    q = sa.select(db.decisions.c.user_id, db.decisions.c.period_end, db.decisions.c.outcome,
                  db.decisions.c.reason_code).order_by(db.decisions.c.id)
    assert a.execute(q).all() == b.execute(q).all()


def test_qa_eval_07_labels_independent():
    tree = ast.parse((ROOT / "src/aqagent/replay/labels.py").read_text())
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
           [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(m.startswith("aqagent.decide") for m in mods)
