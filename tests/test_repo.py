"""Storage (db.py) and data access (repo.py): schema, tz-aware datetimes, revisions, scores, rules."""
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aqagent import db, repo
from aqagent.types import Band, Reading, ReasonCode, StationScore
from tests.fixtures import UTC, hourly

T0 = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
IST = timezone(timedelta(hours=5, minutes=30))
S = 11382


@pytest.fixture
def conn():
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    with engine.begin() as c:
        repo.upsert_station(c, id=4588, city="Helsinki", name="Mannerheimintie", provider="EEA",
                            timezone="Europe/Helsinki", is_reference=True)
        repo.upsert_sensor(c, id=11382, station_id=4588, parameter="pm25", units="µg/m³")
        yield c


def _score(period_end, z=1.0, **kw):
    base = dict(sensor_id=11382, period_end=period_end, z=z, ewma=0.4, cusum=0.0, slope_6h=0.002,
                nowcast=12.3, band=Band.MODERATE, typical_band=Band.GOOD)
    base.update(kw)
    return StationScore(**base)


# --- schema -------------------------------------------------------------------------------------

def test_repo_schema_has_every_table():
    expected = {"stations", "sensors", "readings", "ingestion_runs", "users", "user_rules", "baselines",
                "station_scores", "episodes", "decisions", "notifications", "feedback",
                "held_notices", "run_lock"}
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    assert expected <= set(sa.inspect(engine).get_table_names())
    user_cols = {c["name"] for c in sa.inspect(engine).get_columns("users")}
    assert {"city", "rules_yaml_key", "persona", "station_id"} <= user_cols
    held_cols = {c["name"] for c in sa.inspect(engine).get_columns("held_notices")}
    assert held_cols == {"id", "user_id", "decision_id", "candidate", "held_at", "released_decision_id"}
    assert {c["name"] for c in sa.inspect(engine).get_columns("run_lock")} == {"name", "holder", "acquired_at"}


def test_repo_sqlite_foreign_keys_enforced(conn):
    with pytest.raises(IntegrityError):
        repo.upsert_readings(conn, hourly(T0, [5.0], sensor_id=999), ingested_at=T0, run_id=None)


# --- datetimes ----------------------------------------------------------------------------------

def test_repo_datetimes_round_trip_as_aware_utc(conn):
    # an aware non-UTC input is normalised to UTC; reads come back tz-aware UTC
    end_ist = datetime(2026, 10, 18, 11, 0, tzinfo=IST)  # == 05:30Z
    r = Reading(11382, end_ist, end_ist - timedelta(hours=1), 7.5, 100.0)
    repo.upsert_readings(conn, [r], ingested_at=T0 + timedelta(hours=7), run_id=None)
    [got] = repo.readings_as_of(conn, 11382, T0, T0 + timedelta(days=1), as_of=T0 + timedelta(hours=8))
    assert got.period_end == datetime(2026, 10, 18, 5, 30, tzinfo=UTC)
    assert got.period_end.tzinfo is not None and got.period_end.utcoffset() == timedelta(0)
    assert got.period_start.utcoffset() == timedelta(0)


def test_repo_naive_datetime_rejected(conn):
    naive = datetime(2026, 10, 18, 5, 0)
    with pytest.raises(Exception, match="timezone"):
        repo.upsert_readings(conn, [Reading(11382, naive, naive - timedelta(hours=1), 1.0, 100.0)],
                             ingested_at=T0, run_id=None)


# --- readings with revisions --------------------------------------------------------------------

def test_repo_upsert_readings_new_revised_and_as_of(conn):
    rows = hourly(T0, [10, 11, 12], sensor_id=S)
    assert repo.upsert_readings(conn, rows, ingested_at=T0 + timedelta(hours=3), run_id=None) == (3, 0)
    assert repo.upsert_readings(conn, rows, ingested_at=T0 + timedelta(hours=4), run_id=None) == (0, 0)
    revised = hourly(T0, [10, 99, 12], sensor_id=S)
    assert repo.upsert_readings(conn, revised, ingested_at=T0 + timedelta(hours=5), run_id=None) == (0, 1)

    before = repo.readings_as_of(conn, 11382, T0, T0 + timedelta(hours=2), as_of=T0 + timedelta(hours=4))
    after = repo.readings_as_of(conn, 11382, T0, T0 + timedelta(hours=2), as_of=T0 + timedelta(hours=5))
    assert [r.value for r in before] == [10, 11, 12]
    assert [r.value for r in after] == [10, 99, 12]
    assert [r.period_end for r in after] == [T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2)]
    # nothing known before the first ingestion
    assert repo.readings_as_of(conn, 11382, T0, T0 + timedelta(hours=2), as_of=T0) == []
    assert conn.execute(sa.select(sa.func.count()).select_from(db.readings)).scalar() == 4


def test_repo_readings_as_of_bounds_inclusive(conn):
    repo.upsert_readings(conn, hourly(T0, [1, 2, 3, 4], sensor_id=S), ingested_at=T0 + timedelta(hours=4), run_id=None)
    got = repo.readings_as_of(conn, 11382, T0 + timedelta(hours=1), T0 + timedelta(hours=2),
                              as_of=T0 + timedelta(hours=4))
    assert [r.value for r in got] == [2, 3]


def test_repo_newest_reading_at_respects_as_of(conn):
    repo.upsert_readings(conn, hourly(T0, [1, 2], sensor_id=S), ingested_at=T0 + timedelta(hours=2), run_id=None)
    repo.upsert_readings(conn, hourly(T0 + timedelta(hours=2), [3], sensor_id=S), ingested_at=T0 + timedelta(hours=3),
                         run_id=None)
    assert repo.newest_reading_at(conn, 11382, as_of=T0 + timedelta(hours=2)) == T0 + timedelta(hours=1)
    assert repo.newest_reading_at(conn, 11382, as_of=T0 + timedelta(hours=3)) == T0 + timedelta(hours=2)
    assert repo.newest_reading_at(conn, 11382, as_of=T0) is None


# --- station scores -----------------------------------------------------------------------------

def test_repo_station_scores_round_trip(conn):
    s1 = _score(T0, evidence={"window": [1.0, 2.0], "expected": 4.2})
    s2 = _score(T0 + timedelta(hours=1), z=None, ewma=None, cusum=None, slope_6h=None, nowcast=None,
                band=None, typical_band=Band.VERY_UNHEALTHY, excluded=ReasonCode.DQ_SUSPECT, gap_break=True)
    ids = repo.save_scores(conn, [s1, s2], evaluated_at=T0 + timedelta(hours=2))
    assert len(ids) == 2 and len(set(ids)) == 2

    got = repo.scores_window(conn, 11382, end=T0 + timedelta(hours=1))
    assert got == [s1, s2]
    assert got[1].excluded is ReasonCode.DQ_SUSPECT and got[1].typical_band is Band.VERY_UNHEALTHY
    assert got[0].band is Band.MODERATE
    assert got[0].period_end.utcoffset() == timedelta(0)
    # stored as strings
    row = conn.execute(sa.select(db.station_scores.c.band, db.station_scores.c.excluded)
                       .where(db.station_scores.c.id == ids[1])).one()
    assert row.band is None and row.excluded == "DQ_SUSPECT"
    row = conn.execute(sa.select(db.station_scores.c.band).where(db.station_scores.c.id == ids[0])).one()
    assert row.band == "moderate"


def test_repo_scores_window_latest_evaluation_and_as_of(conn):
    first, second = T0 + timedelta(hours=1), T0 + timedelta(hours=5)
    repo.save_scores(conn, [_score(T0, z=1.0)], evaluated_at=first)
    repo.save_scores(conn, [_score(T0, z=2.0)], evaluated_at=second)
    assert [s.z for s in repo.scores_window(conn, 11382, end=T0)] == [2.0]
    assert [s.z for s in repo.scores_window(conn, 11382, end=T0, as_of=first)] == [1.0]
    assert repo.scores_window(conn, 11382, end=T0, as_of=T0) == []


def test_repo_scores_window_bounds_and_order(conn):
    scores = [_score(T0 + timedelta(hours=h), z=float(h)) for h in range(80)]
    repo.save_scores(conn, list(reversed(scores)), evaluated_at=T0 + timedelta(days=4))
    end = T0 + timedelta(hours=79)
    got = repo.scores_window(conn, 11382, end=end)
    assert len(got) == 72
    assert got[0].period_end == end - timedelta(hours=71) and got[-1].period_end == end
    assert [s.z for s in repo.scores_window(conn, 11382, end=end, hours=3)] == [77.0, 78.0, 79.0]


# --- users and rules ----------------------------------------------------------------------------

def test_repo_upserts_are_idempotent_and_update(conn):
    repo.upsert_user(conn, id="aino-hel", display_name="Aino", station_id=4588, persona={"habits": ["run"]},
                     city="Helsinki", rules_yaml_key="aino")
    repo.upsert_user(conn, id="aino-hel", display_name="Aino K", station_id=4588, persona={}, city="Helsinki")
    row = conn.execute(sa.select(db.users)).one()
    assert (row.display_name, row.persona, row.rules_yaml_key) == ("Aino K", {}, None)
    repo.upsert_station(conn, id=4588, city="Helsinki", name="Renamed", provider="EEA",
                        timezone="Europe/Helsinki", is_reference=True)
    repo.upsert_sensor(conn, id=11382, station_id=4588, parameter="pm25", units="µg/m³")
    assert conn.execute(sa.select(db.stations.c.name)).scalar_one() == "Renamed"
    assert conn.execute(sa.select(sa.func.count()).select_from(db.sensors)).scalar() == 1


def test_repo_rules_versioning(conn):
    repo.upsert_user(conn, id="aino-hel", display_name="Aino", station_id=4588, persona={})
    assert repo.current_rules(conn, "aino-hel") is None
    assert repo.save_rules(conn, "aino-hel", {"sensitivity": "default"}, source="default", at=T0) == 1
    assert repo.save_rules(conn, "aino-hel", {"sensitivity": "high"}, source="user",
                           at=T0 + timedelta(hours=1)) == 2
    assert repo.current_rules(conn, "aino-hel") == (2, {"sensitivity": "high"})
    assert repo.current_rules(conn, "nobody") is None


# --- ingestion runs -----------------------------------------------------------------------------

def test_repo_start_and_finish_run(conn):
    run_id = repo.start_run(conn, kind="hourly", sensor_id=11382, started_at=T0,
                            window_from=T0 - timedelta(hours=24), window_to=T0)
    repo.finish_run(conn, run_id, finished_at=T0 + timedelta(seconds=2), status="ok", rows_fetched=24,
                    rows_new=20, rows_revised=1, newest_period_end=T0 - timedelta(hours=1),
                    ratelimit_remaining=58)
    row = conn.execute(sa.select(db.ingestion_runs).where(db.ingestion_runs.c.id == run_id)).one()
    assert (row.kind, row.status, row.rows_fetched, row.rows_new, row.rows_revised, row.ratelimit_remaining) \
        == ("hourly", "ok", 24, 20, 1, 58)
    assert row.started_at == T0 and row.finished_at == T0 + timedelta(seconds=2)
    assert row.newest_period_end == T0 - timedelta(hours=1) and row.error is None
