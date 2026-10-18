"""Read-only queries behind the API and CLI exports. Every function takes a Connection and returns plain dicts.

Replay isolation: `replay_run=None` means live rows only (decisions.replay_run IS NULL); a run id selects that
replay run only. Notifications inherit their decision's replay_run.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aqagent import repo
from aqagent.db import baselines, decisions as decisions_t, notifications, sensors, station_scores, stations, users

EXPLAIN_READINGS_HOURS = 24  # display window for explain: the 24 hourly readings ending at the decision's hour

EXPORT_COLUMNS = ("delivered_at", "kind", "body", "next_action", "decision_id")


def _replay_filter(replay_run: str | None):
    col = decisions_t.c.replay_run
    return col.is_(None) if replay_run is None else col == replay_run


# --- users and health ----------------------------------------------------------------------------

def list_users(conn: Connection) -> list[dict]:
    q = (sa.select(users.c.id, users.c.display_name, sa.func.coalesce(users.c.city, stations.c.city).label("city"),
                   users.c.station_id, users.c.persona)
         .join(stations, stations.c.id == users.c.station_id)
         .order_by(users.c.id))
    return [dict(r._mapping) for r in conn.execute(q)]


def user_exists(conn: Connection, user_id: str) -> bool:
    return conn.execute(sa.select(users.c.id).where(users.c.id == user_id)).first() is not None


def notification_user(conn: Connection, notification_id: int) -> str | None:
    """The user a notification belongs to, or None if there's no such notification."""
    return conn.execute(sa.select(notifications.c.user_id)
                        .where(notifications.c.id == notification_id)).scalar()


def sensor_freshness(conn: Connection, now: datetime) -> list[dict]:
    """Per sensor: its city, the newest period_end known at `now`, and that reading's age in hours (None if none)."""
    q = (sa.select(sensors.c.id, stations.c.city)
         .join(stations, stations.c.id == sensors.c.station_id)
         .order_by(sensors.c.id))
    out = []
    for sensor_id, city in conn.execute(q):
        newest = repo.newest_reading_at(conn, sensor_id, now)
        age = None if newest is None else (now - newest).total_seconds() / 3600
        out.append({"sensor_id": sensor_id, "city": city, "newest_reading_at": newest, "age_hours": age})
    return out


# --- feed and export -----------------------------------------------------------------------------

def _facts_get(facts: dict | None, dotted: str):
    """`facts["now"]["band"]` for "now.band"; falls back to a flat "now.band" key. None when absent."""
    if not facts:
        return None
    node = facts
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return facts.get(dotted)
        node = node[part]
    return node


def _delivered(user_id: str, replay_run: str | None, until: datetime | None = None):
    n = notifications.c
    q = (sa.select(notifications)
         .join(decisions_t, decisions_t.c.id == n.decision_id)
         .where(n.user_id == user_id, n.delivered_at.is_not(None), _replay_filter(replay_run)))
    if until is not None:
        q = q.where(n.delivered_at <= until)
    return q


def feed(conn: Connection, user_id: str, replay_run: str | None = None,
         until: datetime | None = None) -> list[dict]:
    """Delivered notifications for `user_id`, newest first."""
    n = notifications.c
    q = _delivered(user_id, replay_run, until).order_by(n.delivered_at.desc(), n.id.desc())
    return [{
        "id": r.id, "created_at": r.created_at, "delivered_at": r.delivered_at, "kind": r.kind,
        "event_kind": _facts_get(r.context_facts, "event_kind"), "band": _facts_get(r.context_facts, "now.band"),
        "body": r.body, "next_action": r.next_action, "decision_id": r.decision_id,
    } for r in conn.execute(q)]


def export_rows(conn: Connection, user_id: str, replay_run: str | None = None) -> list[dict]:
    """Delivered notifications for `user_id`, oldest first, with the EXPORT_COLUMNS keys."""
    n = notifications.c
    q = _delivered(user_id, replay_run).order_by(n.delivered_at, n.id)
    return [{k: getattr(r, k) for k in EXPORT_COLUMNS} for r in conn.execute(q)]


# --- decisions and explain -----------------------------------------------------------------------

def decisions(conn: Connection, user_id: str | None = None, start: datetime | None = None,
              end: datetime | None = None, outcome: str | None = None,
              replay_run: str | None = None) -> list[dict]:
    """Decision rows with start <= period_end <= end, in period_end order (then id)."""
    d = decisions_t.c
    q = sa.select(d.id, d.evaluated_at, d.period_end, d.user_id, d.outcome, d.reason_code, d.reason, d.trigger) \
        .where(_replay_filter(replay_run))
    if user_id is not None:
        q = q.where(d.user_id == user_id)
    if start is not None:
        q = q.where(d.period_end >= start)
    if end is not None:
        q = q.where(d.period_end <= end)
    if outcome is not None:
        q = q.where(d.outcome == outcome)
    return [dict(r._mapping) for r in conn.execute(q.order_by(d.period_end, d.id))]


def explain(conn: Connection, notification_id: int) -> dict | None:
    """Everything behind one notification's decision, as known when it was made. None for an unknown id."""
    d = conn.execute(sa.select(decisions_t)
                     .join(notifications, notifications.c.decision_id == decisions_t.c.id)
                     .where(notifications.c.id == notification_id)).first()
    if d is None:
        return None

    score_ids = list(d.score_ids or [])
    scores = []
    if score_ids:
        rows = conn.execute(sa.select(station_scores).where(station_scores.c.id.in_(score_ids)))
        by_id = {r.id: dict(r._mapping) for r in rows}
        scores = [by_id[i] for i in score_ids if i in by_id]

    start = d.period_end - timedelta(hours=EXPLAIN_READINGS_HOURS - 1)
    readings = [asdict(r) for r in repo.readings_as_of(conn, d.sensor_id, start, d.period_end, d.evaluated_at)]

    b = conn.execute(sa.select(baselines)
                     .where(baselines.c.sensor_id == d.sensor_id, baselines.c.fitted_at <= d.evaluated_at)
                     .order_by(baselines.c.fitted_at.desc(), baselines.c.id.desc()).limit(1)).first()

    return {
        "decision": {"outcome": d.outcome, "reason_code": d.reason_code, "reason": d.reason,
                     "evaluated_at": d.evaluated_at, "trigger": d.trigger},
        "trace": d.trace,
        "scores": scores,
        "readings": readings,
        "baseline": None if b is None else dict(b._mapping),
        "rules_version": d.rules_version,
    }
