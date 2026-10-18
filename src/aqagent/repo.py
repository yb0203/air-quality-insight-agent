"""Data access over a SQLAlchemy Connection. The caller owns the transaction.

Enums are stored as their string values (Band.slug, ReasonCode.value) and mapped back on read.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aqagent import params
from aqagent.db import UTC, ingestion_runs, readings, sensors, station_scores, stations, user_rules, users
from aqagent.types import Band, Reading, ReasonCode, StationScore


# --- enum mapping ---------------------------------------------------------------------------------

def _band_out(b: Band | None) -> str | None:
    return None if b is None else Band.parse(b).slug


def _band_in(s: str | None) -> Band | None:
    return None if s is None else Band.parse(s)


def _code_out(c: ReasonCode | None) -> str | None:
    return None if c is None else ReasonCode(c).value


def _code_in(s: str | None) -> ReasonCode | None:
    return None if s is None else ReasonCode(s)


# --- generic upsert (portable: SQLite and Postgres) -----------------------------------------------

def _upsert(conn: Connection, table: sa.Table, key: dict, values: dict) -> None:
    where = sa.and_(*(table.c[k] == v for k, v in key.items()))
    if conn.execute(sa.select(sa.literal(1)).select_from(table).where(where)).first():
        conn.execute(table.update().where(where).values(**values))
    else:
        conn.execute(table.insert().values(**key, **values))


def upsert_station(conn: Connection, *, id: int, city: str, name: str, provider: str, timezone: str,
                   is_reference: bool, instrument: str | None = None, lat: float | None = None,
                   lon: float | None = None, license: str | None = None, attribution: str | None = None,
                   active: bool = True) -> None:
    _upsert(conn, stations, {"id": id}, dict(
        city=city, name=name, provider=provider, timezone=timezone, is_reference=is_reference,
        instrument=instrument, lat=lat, lon=lon, license=license, attribution=attribution, active=active))


def upsert_sensor(conn: Connection, *, id: int, station_id: int, parameter: str, units: str) -> None:
    _upsert(conn, sensors, {"id": id}, dict(station_id=station_id, parameter=parameter, units=units))


def upsert_user(conn: Connection, *, id: str, display_name: str, station_id: int, persona: dict,
                city: str | None = None, rules_yaml_key: str | None = None) -> None:
    _upsert(conn, users, {"id": id}, dict(display_name=display_name, station_id=station_id, persona=persona,
                                          city=city, rules_yaml_key=rules_yaml_key))


# --- readings (append-only revisions) ------------------------------------------------------------

def _latest_versions(sensor_id: int, as_of: datetime | None):
    """Subquery: per period_end of `sensor_id`, the max ingested_at (<= as_of when given)."""
    q = (sa.select(readings.c.period_end, sa.func.max(readings.c.ingested_at).label("ingested_at"))
         .where(readings.c.sensor_id == sensor_id))
    if as_of is not None:
        q = q.where(readings.c.ingested_at <= as_of)
    return q.group_by(readings.c.period_end).subquery()


def _current(conn: Connection, sensor_id: int, start: datetime, end: datetime,
             as_of: datetime | None) -> list[sa.Row]:
    latest = _latest_versions(sensor_id, as_of)
    q = (sa.select(readings)
         .join(latest, sa.and_(readings.c.period_end == latest.c.period_end,
                               readings.c.ingested_at == latest.c.ingested_at))
         .where(readings.c.sensor_id == sensor_id, readings.c.period_end >= start, readings.c.period_end <= end)
         .order_by(readings.c.period_end))
    return list(conn.execute(q))


def upsert_readings_detailed(conn: Connection, rows: list[Reading], ingested_at: datetime,
                             run_id: int | None) -> tuple[list[datetime], list[datetime]]:
    """Store `rows`; returns (new period_ends, revised period_ends), each ascending.

    A row is written only when (sensor_id, period_end) is new, or its value or coverage changed from the
    latest stored version (a revision; the old version is kept). Unchanged rows are a no-op.
    """
    new: list[datetime] = []
    revised: list[datetime] = []
    by_sensor: dict[int, dict[datetime, Reading]] = {}
    for r in rows:
        by_sensor.setdefault(r.sensor_id, {})[r.period_end] = r  # later duplicates win
    for sensor_id, batch in by_sensor.items():
        ends = sorted(batch)
        stored = {row.period_end: row for row in _current(conn, sensor_id, ends[0], ends[-1], None)}
        inserts = []
        for end in ends:
            r = batch[end]
            prev = stored.get(end)  # aware datetimes hash by their UTC instant
            if prev is not None and (prev.value, prev.coverage_pct) == (r.value, r.coverage_pct):
                continue
            values = dict(sensor_id=sensor_id, period_end=r.period_end, period_start=r.period_start,
                          value=r.value, coverage_pct=r.coverage_pct, ingested_at=ingested_at, run_id=run_id)
            if prev is not None and prev.ingested_at == ingested_at:
                # same instant as the latest version: amend it rather than violate the primary key
                conn.execute(readings.update().where(
                    readings.c.sensor_id == sensor_id, readings.c.period_end == r.period_end,
                    readings.c.ingested_at == ingested_at).values(**values))
            else:
                inserts.append(values)
            (revised if prev is not None else new).append(end.astimezone(UTC))
        if inserts:
            conn.execute(readings.insert(), inserts)
    return sorted(new), sorted(revised)


def upsert_readings(conn: Connection, rows: list[Reading], ingested_at: datetime,
                    run_id: int | None) -> tuple[int, int]:
    """Store `rows` as of `ingested_at`. Returns (new, revised) counts."""
    new, revised = upsert_readings_detailed(conn, rows, ingested_at, run_id)
    return len(new), len(revised)


def readings_as_of(conn: Connection, sensor_id: int, start: datetime, end: datetime,
                   as_of: datetime) -> list[Reading]:
    """Latest version known at `as_of` of each hour with start <= period_end <= end, ascending."""
    return [Reading(r.sensor_id, r.period_end, r.period_start, r.value, r.coverage_pct)
            for r in _current(conn, sensor_id, start, end, as_of)]


def newest_reading_at(conn: Connection, sensor_id: int, as_of: datetime) -> datetime | None:
    """The newest period_end of `sensor_id` known at `as_of` (ingested_at <= as_of), or None."""
    q = sa.select(sa.func.max(readings.c.period_end)).where(
        readings.c.sensor_id == sensor_id, readings.c.ingested_at <= as_of)
    return conn.execute(q).scalar()


# --- station scores ------------------------------------------------------------------------------

def save_scores(conn: Connection, scores: list[StationScore], evaluated_at: datetime,
                baseline_id: int | None = None) -> list[int]:
    """Insert one station_scores row per score (same order); returns their ids."""
    ids = []
    for s in scores:
        res = conn.execute(station_scores.insert().values(
            sensor_id=s.sensor_id, period_end=s.period_end, evaluated_at=evaluated_at, baseline_id=baseline_id,
            z=s.z, ewma=s.ewma, cusum=s.cusum, slope_6h=s.slope_6h, nowcast=s.nowcast,
            band=_band_out(s.band), typical_band=_band_out(s.typical_band), excluded=_code_out(s.excluded),
            gap_break=s.gap_break, evidence=s.evidence or {}))
        ids.append(res.inserted_primary_key[0])
    return ids


def _score_window_rows(conn: Connection, sensor_id: int, end: datetime, hours: int,
                       as_of: datetime | None) -> list[sa.Row]:
    start = end - timedelta(hours=hours)
    sc = station_scores.c
    latest = sa.select(sc.period_end, sa.func.max(sc.evaluated_at).label("evaluated_at")).where(
        sc.sensor_id == sensor_id, sc.period_end > start, sc.period_end <= end)
    if as_of is not None:
        latest = latest.where(sc.evaluated_at <= as_of)
    latest = latest.group_by(sc.period_end).subquery()
    q = (sa.select(station_scores)
         .join(latest, sa.and_(sc.period_end == latest.c.period_end, sc.evaluated_at == latest.c.evaluated_at))
         .where(sc.sensor_id == sensor_id)
         .order_by(sc.period_end))
    return list(conn.execute(q))


def _score_from_row(r: sa.Row) -> StationScore:
    return StationScore(sensor_id=r.sensor_id, period_end=r.period_end, z=r.z, ewma=r.ewma, cusum=r.cusum,
                        slope_6h=r.slope_6h, nowcast=r.nowcast, band=_band_in(r.band),
                        typical_band=_band_in(r.typical_band), excluded=_code_in(r.excluded),
                        gap_break=bool(r.gap_break), evidence=r.evidence or {})


def scores_window(conn: Connection, sensor_id: int, end: datetime, hours: int = params.SCORE_WINDOW_HOURS,
                  as_of: datetime | None = None) -> list[StationScore]:
    """Scores with end - hours < period_end <= end; the latest evaluation (<= as_of if given) per hour, ascending."""
    return [_score_from_row(r) for r in _score_window_rows(conn, sensor_id, end, hours, as_of)]


def score_ids_window(conn: Connection, sensor_id: int, end: datetime, hours: int = params.SCORE_WINDOW_HOURS,
                     as_of: datetime | None = None) -> list[int]:
    """The station_scores ids behind `scores_window` with the same arguments, same order (for decisions.score_ids)."""
    return [r.id for r in _score_window_rows(conn, sensor_id, end, hours, as_of)]


# --- user rules ----------------------------------------------------------------------------------

def save_rules(conn: Connection, user_id: str, rules: dict, source: str, at: datetime) -> int:
    """Append a new rules version for `user_id`; returns it (1 for the first)."""
    current = conn.execute(sa.select(sa.func.max(user_rules.c.version))
                           .where(user_rules.c.user_id == user_id)).scalar()
    version = (current or 0) + 1
    conn.execute(user_rules.insert().values(user_id=user_id, version=version, source=source, rules=rules,
                                            created_at=at))
    return version


def current_rules(conn: Connection, user_id: str) -> tuple[int, dict] | None:
    row = conn.execute(sa.select(user_rules.c.version, user_rules.c.rules)
                       .where(user_rules.c.user_id == user_id)
                       .order_by(user_rules.c.version.desc()).limit(1)).first()
    return None if row is None else (row.version, row.rules)


# --- ingestion runs ------------------------------------------------------------------------------

def start_run(conn: Connection, *, kind: str, started_at: datetime, sensor_id: int | None = None,
              window_from: datetime | None = None, window_to: datetime | None = None) -> int:
    res = conn.execute(ingestion_runs.insert().values(
        kind=kind, sensor_id=sensor_id, started_at=started_at, window_from=window_from, window_to=window_to,
        status="running"))
    return res.inserted_primary_key[0]


def finish_run(conn: Connection, run_id: int, *, finished_at: datetime, status: str,
               rows_fetched: int | None = None, rows_new: int | None = None, rows_revised: int | None = None,
               newest_period_end: datetime | None = None, error: str | None = None,
               ratelimit_remaining: int | None = None) -> None:
    conn.execute(ingestion_runs.update().where(ingestion_runs.c.id == run_id).values(
        finished_at=finished_at, status=status, rows_fetched=rows_fetched, rows_new=rows_new,
        rows_revised=rows_revised, newest_period_end=newest_period_end, error=error,
        ratelimit_remaining=ratelimit_remaining))
