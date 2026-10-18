"""REPLAY (S-C §12): drive the real runner through past hours on a simulated clock, then score the result.

Readings are loaded with the time they would have arrived (`ingested_at`), so at each simulated tick the
pipeline sees exactly what it would have known live. Replays use their own database.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa

from aqagent import db
from aqagent.clock import FixedClock
from aqagent.runner import RunSummary, clock_tick, data_run, users_for

HOUR = timedelta(hours=1)
TICK_MINUTE = 20
CATCH_WINDOW = timedelta(hours=6)


@dataclass
class ReplaySummary:
    run_id: str
    ticks: int
    decisions: int
    sent: int
    held: int


def _ticks(start: datetime, end: datetime) -> list[datetime]:
    t = start.replace(minute=TICK_MINUTE, second=0, microsecond=0)
    if t < start:
        t += HOUR
    out = []
    while t <= end:
        out.append(t)
        t += HOUR
    return out


def schedule(conn: sa.Connection, start: datetime, end: datetime) -> list[tuple[datetime, str, list[str] | None]]:
    """Every clock event in [start, end]: hourly ticks, plus each user's check-ins and quiet-hours ends."""
    events: list[tuple[datetime, int, str, list[str] | None]] = [(t, 0, "hourly", None) for t in _ticks(start, end)]
    for user in users_for(conn):
        if user.rules.check_in.cron:
            t = start
            while (t := user.rules.next_check_in(t, user.tz)) is not None and t <= end:
                events.append((t, 1, "check_in", [user.id]))
        local = start.astimezone(user.tz)
        while (q := user.rules.quiet_end_after(local)).astimezone(start.tzinfo) <= end:
            events.append((q.astimezone(start.tzinfo), 2, "quiet_end", [user.id]))
            local = q
    events.sort(key=lambda e: (e[0], e[1]))
    return [(t, kind, users) for t, _order, kind, users in events]


def _arrived(conn: sa.Connection, after: datetime | None, until: datetime) -> dict[int, list[datetime]]:
    r = db.readings
    q = sa.select(r.c.sensor_id, r.c.period_end).where(r.c.ingested_at <= until)
    if after is not None:
        q = q.where(r.c.ingested_at > after)
    changed: dict[int, set[datetime]] = {}
    for sensor_id, period_end in conn.execute(q):
        changed.setdefault(sensor_id, set()).add(period_end)
    return {k: sorted(v) for k, v in changed.items()}


def replay(conn: sa.Connection, start: datetime, end: datetime, run_id: str, llm=None) -> ReplaySummary:
    clock = FixedClock(start)
    total = RunSummary()
    ticks = 0
    last_tick: datetime | None = None
    for t, kind, users in schedule(conn, start, end):
        clock.set(t)
        if kind == "hourly":
            changed = _arrived(conn, last_tick if last_tick is not None else start - timedelta(days=120), t)
            s = data_run(conn, changed, clock, llm, replay_run=run_id)
            last_tick = t
            ticks += 1
            _merge(total, s)
        s = clock_tick(conn, clock, llm, kind, users, replay_run=run_id)
        _merge(total, s)
    return ReplaySummary(run_id, ticks, total.decisions, total.sent, total.held)


def _merge(total: RunSummary, s: RunSummary) -> None:
    total.decisions += s.decisions
    total.sent += s.sent
    total.held += s.held
    total.scored += s.scored


def report(conn: sa.Connection, run_id: str, moments_by_location: dict[int, list], start: datetime,
           end: datetime) -> dict:
    """Per station and user: caught / missed / false alarms against reference moments, plus volume."""
    d, n, u = db.decisions, db.notifications, db.users
    weeks = max((end - start) / timedelta(days=7), 1e-9)
    out: dict[str, dict] = {}
    for user in conn.execute(sa.select(u.c.id, u.c.station_id, u.c.city)).mappings():
        uid, station = user["id"], user["station_id"]
        rows = conn.execute(sa.select(d.c.period_end, d.c.outcome, d.c.reason_code, d.c.trace, n.c.kind)
                            .join(n, n.c.decision_id == d.c.id, isouter=True)
                            .where(d.c.user_id == uid, d.c.replay_run == run_id)).mappings().all()
        spoke = [r for r in rows if r["outcome"] in ("sent", "held")]
        sent = [r for r in rows if r["outcome"] == "sent"]
        opened = [r for r in sent if r["kind"] == "opened"]
        moments = [m for m in moments_by_location.get(station, []) if start <= m.start <= end]
        positives = [m for m in moments if m.kind == "positive"]
        negatives = [m for m in moments if m.kind == "negative"]

        caught, delays, missed = 0, [], []
        for m in positives:
            # caught = said something within 6h either side of the onset (an early catch counts)
            hits = [r["period_end"] for r in spoke if m.start - CATCH_WINDOW <= r["period_end"] <= m.start + CATCH_WINDOW]
            if hits:
                caught += 1
                delays.append((min(hits) - m.start) / HOUR)  # negative = before the labelled onset
            else:
                missed.append(m)
        false_alarms = sum(1 for r in opened
                           if not any(abs((r["period_end"] - m.start) / HOUR) <= CATCH_WINDOW / HOUR for m in positives))
        glitch_notices = sum(1 for r in sent for m in negatives if m.start <= r["period_end"] <= m.end)
        near = {}
        for m in missed:
            best = 0
            for r in rows:
                if m.start - HOUR <= r["period_end"] <= m.start + CATCH_WINDOW:
                    for step in r["trace"] or []:
                        if step.get("layer") == "D1":
                            best = max(best, len(step.get("values", {}).get("near_misses") or []))
            near[m.start.isoformat()] = best
        by_kind: dict[str, int] = {}
        for r in sent:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        events = len(sent) - by_kind.get("check_in", 0)
        out[uid] = {
            "station_id": station, "city": user["city"], "moments": len(positives), "caught": caught,
            "by_kind": by_kind, "event_notices_per_week": round(events / weeks, 2),
            "missed": len(missed), "false_alarms": false_alarms, "glitch_notices": glitch_notices,
            "notices": len(sent), "notices_per_week": round(len(sent) / weeks, 2),
            "median_time_to_notify_h": round(statistics.median(delays), 1) if delays else None,
            "near_misses_by_missed": near,
        }
    return out
