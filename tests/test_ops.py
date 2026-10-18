"""Task 14: the hourly tick, its overlap lock and the scheduler (plain functions in aqagent.ops)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aqagent import db, ops
from aqagent.clock import FixedClock
from aqagent.types import Reading

UTC = timezone.utc
NOW = datetime(2026, 10, 18, 6, 20, tzinfo=UTC)


class FakeOpenAQ:
    last_ratelimit_remaining = 1999

    def __init__(self):
        self.calls = 0

    def hours(self, sensor_id, dt_from, dt_to):
        self.calls += 1
        dt_from = max(dt_from, dt_to - timedelta(hours=48))  # keep the fake small
        out, t = [], dt_from.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        while t <= dt_to - timedelta(minutes=30):
            out.append(Reading(sensor_id, t, t - timedelta(hours=1), 10.0 + (t.hour % 5), 100.0))
            t += timedelta(hours=1)
        return out


def seeded(tmp_path):
    url = f"sqlite:///{tmp_path / 'live.db'}"
    engine = db.make_engine(url)
    ops.init_db(engine)
    ops.seed(engine, NOW)
    return engine


def test_seed_loads_tracked_stations_and_users(tmp_path):
    engine = seeded(tmp_path)
    with engine.connect() as c:
        cities = {r for (r,) in c.execute(sa.select(db.stations.c.city))}
        users = {r for (r,) in c.execute(sa.select(db.users.c.id))}
    assert cities == {"Helsinki", "Los Angeles", "Bengaluru", "Dubai", "Delhi"}
    assert users == {"arjun", "meera", "priya", "omar", "maya", "aino"}


def test_tick_ingests_scores_and_decides(tmp_path):
    engine = seeded(tmp_path)
    fake = FakeOpenAQ()
    out = ops.tick(engine, FixedClock(NOW), fake, llm=None)
    assert out["status"] == "ok" and fake.calls == 5
    with engine.connect() as c:
        assert c.execute(sa.select(sa.func.count()).select_from(db.ingestion_runs)).scalar() == 5
        assert c.execute(sa.select(sa.func.count()).select_from(db.decisions)).scalar() > 0


def test_review_scheduler_no_overlap(tmp_path):
    engine = seeded(tmp_path)
    sched = ops.build_scheduler(engine, client=FakeOpenAQ(), llm=None)
    hourly = sched.get_job("hourly")
    assert hourly.max_instances == 1 and hourly.coalesce is True
    assert {j.id for j in sched.get_jobs()} >= {"hourly", "check_in:arjun", "quiet_end:aino"}
    # a second tick while the first holds the lock is skipped, so nothing is ingested or sent twice
    with engine.begin() as c:
        assert ops.acquire_lock(c, "tick", "other-process", NOW)
    fake = FakeOpenAQ()
    out = ops.tick(engine, FixedClock(NOW), fake, llm=None)
    assert out["status"] == "skipped" and fake.calls == 0


def test_stale_lock_is_taken_over(tmp_path):
    engine = seeded(tmp_path)
    with engine.begin() as c:
        assert ops.acquire_lock(c, "tick", "crashed", NOW - timedelta(hours=2))
    out = ops.tick(engine, FixedClock(NOW), FakeOpenAQ(), llm=None)
    assert out["status"] == "ok"
