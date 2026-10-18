"""SQLAlchemy Core schema (S-A §5, plus held_notices and run_lock) and the engine factory.

Every timestamp column is `UTCDateTime`: writes must be timezone-aware (converted to UTC), and reads
always come back as timezone-aware UTC, on SQLite as well as Postgres.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

UTC = timezone.utc


class UTCDateTime(TypeDecorator):
    """`DateTime(timezone=True)` that rejects naive values and always returns aware UTC."""

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected a datetime, got {type(value).__name__}")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"naive datetime {value!r}: every timestamp must be timezone-aware UTC")
        value = value.astimezone(UTC)
        # SQLite has no timezone storage; store naive UTC so string comparison stays chronological.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def _json_dumps(obj) -> str:
    return json.dumps(obj, default=_json_default)


TS = UTCDateTime
metadata = sa.MetaData()

# Reference data -----------------------------------------------------------------------------------

stations = sa.Table(
    "stations", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),  # OpenAQ location id
    sa.Column("city", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("instrument", sa.Text),
    sa.Column("is_reference", sa.Boolean, nullable=False),
    sa.Column("timezone", sa.Text, nullable=False),
    sa.Column("lat", sa.Float),
    sa.Column("lon", sa.Float),
    sa.Column("license", sa.Text),
    sa.Column("attribution", sa.Text),
    sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
)

sensors = sa.Table(
    "sensors", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),  # OpenAQ sensor id
    sa.Column("station_id", sa.Integer, sa.ForeignKey("stations.id"), nullable=False),
    sa.Column("parameter", sa.Text, nullable=False),
    sa.Column("units", sa.Text, nullable=False),
    sa.UniqueConstraint("station_id", "parameter"),
)

ingestion_runs = sa.Table(
    "ingestion_runs", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("started_at", TS, nullable=False),
    sa.Column("finished_at", TS),
    sa.Column("kind", sa.Text, nullable=False),  # 'hourly' | 'backfill' | 'replay-load'
    sa.Column("sensor_id", sa.Integer, sa.ForeignKey("sensors.id")),
    sa.Column("window_from", TS),
    sa.Column("window_to", TS),
    sa.Column("rows_fetched", sa.Integer),
    sa.Column("rows_new", sa.Integer),
    sa.Column("rows_revised", sa.Integer),
    sa.Column("newest_period_end", TS),
    sa.Column("status", sa.Text, nullable=False),  # 'running' | 'ok' | 'partial' | 'error'
    sa.Column("error", sa.Text),
    sa.Column("ratelimit_remaining", sa.Integer),
)

# Append-only revisions: "as of T" = per (sensor_id, period_end), the row with max ingested_at <= T.
readings = sa.Table(
    "readings", metadata,
    sa.Column("sensor_id", sa.Integer, sa.ForeignKey("sensors.id"), primary_key=True),
    sa.Column("period_end", TS, primary_key=True),
    sa.Column("period_start", TS, nullable=False),
    sa.Column("value", sa.Float),
    sa.Column("coverage_pct", sa.Float),
    sa.Column("ingested_at", TS, primary_key=True),
    sa.Column("run_id", sa.Integer, sa.ForeignKey("ingestion_runs.id")),
)

# Users and rules ----------------------------------------------------------------------------------

users = sa.Table(
    "users", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("station_id", sa.Integer, sa.ForeignKey("stations.id"), nullable=False),
    sa.Column("persona", sa.JSON, nullable=False),
    sa.Column("city", sa.Text),
    sa.Column("rules_yaml_key", sa.Text, nullable=True),
)

user_rules = sa.Table(
    "user_rules", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("source", sa.Text, nullable=False),  # 'default' | 'user' | 'learned'
    sa.Column("rules", sa.JSON, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.UniqueConstraint("user_id", "version"),
)

# Detection ----------------------------------------------------------------------------------------

baselines = sa.Table(
    "baselines", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("sensor_id", sa.Integer, sa.ForeignKey("sensors.id"), nullable=False),
    sa.Column("fitted_at", TS, nullable=False),
    sa.Column("trained_through", TS, nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("params", sa.JSON, nullable=False),
)

station_scores = sa.Table(
    "station_scores", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("sensor_id", sa.Integer, sa.ForeignKey("sensors.id"), nullable=False),
    sa.Column("period_end", TS, nullable=False),
    sa.Column("evaluated_at", TS, nullable=False),
    sa.Column("baseline_id", sa.Integer, sa.ForeignKey("baselines.id")),
    sa.Column("z", sa.Float),
    sa.Column("ewma", sa.Float),
    sa.Column("cusum", sa.Float),
    sa.Column("slope_6h", sa.Float),
    sa.Column("nowcast", sa.Float),
    sa.Column("band", sa.Text),          # Band.slug
    sa.Column("typical_band", sa.Text),  # Band.slug
    sa.Column("excluded", sa.Text),      # ReasonCode value from S2, NULL = usable (StationScore.excluded)
    sa.Column("gap_break", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("quality", sa.JSON),
    sa.Column("evidence", sa.JSON, nullable=False),
    sa.UniqueConstraint("sensor_id", "period_end", "evaluated_at"),
)

# Episodes, decisions, notifications ---------------------------------------------------------------

episodes = sa.Table(
    "episodes", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("sensor_id", sa.Integer, sa.ForeignKey("sensors.id"), nullable=False),
    sa.Column("opened_at", TS, nullable=False),
    sa.Column("closed_at", TS),
    sa.Column("state", sa.Text, nullable=False),  # NORMAL | ACTIVE | RECOVERING | CLOSED
    sa.Column("close_reason", sa.Text),
    sa.Column("peak_value", sa.Float),
    sa.Column("peak_band", sa.Text),
    sa.Column("last_notified_at", TS),
    sa.Column("last_notified_band", sa.Text),
    sa.Column("last_notified_kind", sa.Text),
    sa.Column("notifications_sent", sa.Integer, nullable=False, server_default="0"),
    sa.Column("cooldown_until", TS),
    sa.Column("kinds", sa.JSON, nullable=False, default=list),  # event kinds seen in this episode
    sa.Column("last_hour", TS),  # latest period_end processed by D2 (late-hour guard)
)

decisions = sa.Table(
    "decisions", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("evaluated_at", TS, nullable=False),
    sa.Column("period_end", TS, nullable=False),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("sensor_id", sa.Integer, sa.ForeignKey("sensors.id"), nullable=False),
    sa.Column("rules_version", sa.Integer, nullable=False),
    sa.Column("episode_id", sa.Integer, sa.ForeignKey("episodes.id")),
    sa.Column("score_ids", sa.JSON),
    sa.Column("outcome", sa.Text, nullable=False),      # Outcome value
    sa.Column("reason_code", sa.Text, nullable=False),  # ReasonCode value
    sa.Column("trigger", sa.Text, nullable=False, server_default="data"),  # 'data' | 'clock'
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("trace", sa.JSON, nullable=False),
    sa.Column("replay_run", sa.Text),
    sa.Index("ix_decisions_user_period", "user_id", "period_end"),
)

notifications = sa.Table(
    "notifications", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("decision_id", sa.Integer, sa.ForeignKey("decisions.id"), nullable=False),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("deliver_after", TS, nullable=False),
    sa.Column("delivered_at", TS),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("body", sa.Text, nullable=False),
    sa.Column("next_action", sa.Text, nullable=False),
    sa.Column("context_facts", sa.JSON, nullable=False),
    sa.Column("generator", sa.Text, nullable=False),  # 'llm:<model>' | 'template'
)

held_notices = sa.Table(
    "held_notices", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("decision_id", sa.Integer, sa.ForeignKey("decisions.id"), nullable=False),
    sa.Column("candidate", sa.JSON, nullable=False),
    sa.Column("held_at", TS, nullable=False),
    sa.Column("released_decision_id", sa.Integer, sa.ForeignKey("decisions.id"), nullable=True),
)

feedback = sa.Table(
    "feedback", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("notification_id", sa.Integer, sa.ForeignKey("notifications.id"), nullable=False),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("action", sa.Text, nullable=False),  # 'acted' | 'dismissed' | 'not_useful'
    sa.Column("at", TS, nullable=False),
)

run_lock = sa.Table(
    "run_lock", metadata,
    sa.Column("name", sa.Text, primary_key=True),
    sa.Column("holder", sa.Text, nullable=False),
    sa.Column("acquired_at", TS, nullable=False),
)


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def make_engine(url: str) -> Engine:
    """Engine for `url`. SQLite: usable across threads, foreign keys on; in-memory DBs share one connection."""
    u = sa.make_url(url)
    if u.get_backend_name() != "sqlite":
        return sa.create_engine(url, json_serializer=_json_dumps, pool_pre_ping=True)
    kwargs: dict = {"connect_args": {"check_same_thread": False}, "json_serializer": _json_dumps}
    if u.database in (None, "", ":memory:"):
        kwargs["poolclass"] = StaticPool
    else:
        Path(u.database).parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(url, **kwargs)
    sa.event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_all(engine: Engine) -> None:
    metadata.create_all(engine)
