"""Operations as plain Python functions: set up the database, the hourly tick, the scheduler, replaying the sample.

Run them from the small scripts in scripts/ (no CLI)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import sqlalchemy as sa

from aqagent import db, params
from aqagent.clock import Clock, SystemClock
from aqagent.replay.load import TRACKED, load_sample, load_stations
from aqagent.runner import clock_tick, data_run, users_for
from aqagent.seed import seed_users
from aqagent.sense.ingest import run_ingestion

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
DEFAULT_DB = f"sqlite:///{ROOT / 'data' / 'aqagent.db'}"
LOCK_STALE = timedelta(hours=1)


# --- building blocks (importable, tested) ---------------------------------------------------------

def init_db(engine: sa.Engine) -> None:
    db.create_all(engine)


def seed(engine: sa.Engine, at: datetime) -> int:
    with engine.begin() as conn:
        load_stations(conn, SAMPLES / "stations.json", location_ids=TRACKED)
        return seed_users(conn, at)


def acquire_lock(conn: sa.Connection, name: str, holder: str, at: datetime) -> bool:
    """One tick at a time. A lock older than an hour is assumed dead and taken over."""
    lock = db.run_lock
    row = conn.execute(sa.select(lock).where(lock.c.name == name)).first()
    if row is None:
        conn.execute(lock.insert().values(name=name, holder=holder, acquired_at=at))
        return True
    if at - row.acquired_at >= LOCK_STALE:
        conn.execute(lock.update().where(lock.c.name == name).values(holder=holder, acquired_at=at))
        return True
    return False


def release_lock(conn: sa.Connection, name: str, holder: str) -> None:
    conn.execute(db.run_lock.delete().where(db.run_lock.c.name == name, db.run_lock.c.holder == holder))


def tracked_sensors(conn: sa.Connection) -> list[int]:
    s = db.sensors
    return [r for (r,) in conn.execute(sa.select(s.c.id).where(s.c.station_id.in_(TRACKED), s.c.parameter == "pm25"))]


def tick(engine: sa.Engine, clock: Clock, client, llm=None) -> dict:
    """One hourly run: ingest (with automatic backfill), score and decide, then the hourly clock tick."""
    holder = f"pid-{os.getpid()}"
    with engine.begin() as conn:
        if not acquire_lock(conn, "tick", holder, clock.now()):
            return {"status": "skipped", "reason": "another tick holds the lock"}
    try:
        with engine.begin() as conn:
            report = run_ingestion(conn, client, clock, tracked_sensors(conn))
        with engine.begin() as conn:
            data = data_run(conn, report.changed, clock, llm)
            tick_ = clock_tick(conn, clock, llm, "hourly")
        return {"status": "ok", "new": report.new, "revised": report.revised, "errors": report.errors,
                "decisions": data.decisions + tick_.decisions, "sent": data.sent, "held": data.held}
    finally:
        with engine.begin() as conn:
            release_lock(conn, "tick", holder)


def _clock_job(engine: sa.Engine, llm, event: str, user_id: str) -> None:
    with engine.begin() as conn:
        clock_tick(conn, SystemClock(), llm, event, [user_id])


def build_scheduler(engine: sa.Engine, client, llm=None, blocking: bool = False):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = (BlockingScheduler if blocking else BackgroundScheduler)(timezone="UTC")
    common = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 600}
    sched.add_job(lambda: tick(engine, SystemClock(), client, llm), CronTrigger(minute=20, timezone="UTC"),
                  id="hourly", **common)
    with engine.connect() as conn:
        users = users_for(conn)
    for u in users:
        if u.rules.check_in.cron:
            sched.add_job(_clock_job, CronTrigger.from_crontab(u.rules.check_in.cron, timezone=u.tz),
                          args=[engine, llm, "check_in", u.id], id=f"check_in:{u.id}", **common)
        end = u.rules.quiet_hours.end
        sched.add_job(_clock_job, CronTrigger(hour=end.hour, minute=end.minute, timezone=u.tz),
                      args=[engine, llm, "quiet_end", u.id], id=f"quiet_end:{u.id}", **common)
    return sched


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader (no dependency): KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def replay_sample(url: str, days: int, run_id: str, llm=None) -> dict:
    """Load the shipped sample into a fresh database, replay its last `days` days, return the report."""
    from aqagent.replay.harness import replay, report
    from aqagent.replay.labels import all_moments

    engine = db.make_engine(url)
    db.metadata.drop_all(engine)
    db.create_all(engine)
    with engine.begin() as conn:
        load_sample(conn, SAMPLES / "openaq_pm25_hourly_90d.csv", SAMPLES / "stations.json")
        r = db.readings
        end = conn.execute(sa.select(sa.func.max(r.c.ingested_at))).scalar() + timedelta(hours=1)
        start = end - timedelta(days=days)
        seed_users(conn, start)
        summary = replay(conn, start, end, run_id, llm)
        rep = report(conn, run_id, all_moments(conn, ROOT / "data" / "labels.yaml"), start, end)
    return {"summary": summary.__dict__, "start": start.isoformat(), "end": end.isoformat(), "users": rep}


# --- live dependencies ---------------------------------------------------------------------------

def openaq_client():
    from aqagent.sense.openaq import OpenAQClient

    return OpenAQClient(os.environ.get("OPENAQ_API_KEY", ""))


def llm_from_env():
    from aqagent.act.compose import anthropic_llm

    return anthropic_llm(os.environ.get("AQAGENT_LLM_MODEL") or params.DEFAULT_LLM_MODEL)

