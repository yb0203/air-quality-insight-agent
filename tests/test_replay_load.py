"""REPLAY (Task 13, runner-free part): the as-known sample loader and the reference labels."""
import ast
import csv
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa

from aqagent import db, repo
from aqagent.replay import labels, load
from tests.fixtures import SAMPLE_CSV, UTC, sample_readings

ROOT = Path(__file__).resolve().parent.parent
STATIONS_JSON = ROOT / "data" / "samples" / "stations.json"
LABELS_YAML = ROOT / "data" / "labels.yaml"
LABELS_PY = ROOT / "src" / "aqagent" / "replay" / "labels.py"
HELSINKI_TZ = ZoneInfo("Europe/Helsinki")


def _csv_rows() -> list[dict]:
    with SAMPLE_CSV.open() as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def loaded():
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    with engine.begin() as c:
        n = load.load_sample(c, SAMPLE_CSV, STATIONS_JSON)
    with engine.connect() as c:
        yield c, n


# --- loader ---------------------------------------------------------------------------------------

def test_load_sample_row_count_matches_csv(loaded):
    conn, n = loaded
    expected = len(_csv_rows())
    assert n == expected
    assert conn.execute(sa.select(sa.func.count()).select_from(db.readings)).scalar() == expected


def test_load_sample_stations_and_sensors(loaded):
    conn, _ = loaded
    cities = dict(conn.execute(sa.select(db.stations.c.id, db.stations.c.city)).all())
    assert cities[4588] == "Helsinki"
    assert cities[8039] == "Mumbai (glitch fixture)"
    assert cities[8118] == "Delhi (AirNow reference)"
    assert set(cities) == load.TRACKED | load.FIXTURES
    sensors = dict(conn.execute(sa.select(db.sensors.c.id, db.sensors.c.station_id)).all())
    assert sensors[11382] == 4588
    assert conn.execute(sa.select(sa.func.count()).select_from(db.sensors)
                        .where(db.sensors.c.parameter != "pm25")).scalar() == 0


def test_load_sample_records_one_replay_load_run(loaded):
    conn, n = loaded
    runs = conn.execute(sa.select(db.ingestion_runs)).all()
    assert len(runs) == 1
    assert runs[0].kind == "replay-load" and runs[0].status == "ok" and runs[0].rows_new == n
    assert conn.execute(sa.select(sa.func.count()).select_from(db.readings)
                        .where(db.readings.c.run_id != runs[0].id)).scalar() == 0


def test_load_sample_is_as_known(loaded):
    conn, _ = loaded
    hour = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)
    before = repo.readings_as_of(conn, 11382, hour, hour, as_of=hour + timedelta(hours=1))
    after = repo.readings_as_of(conn, 11382, hour, hour, as_of=hour + timedelta(hours=2))
    assert before == []
    assert [r.value for r in after] == [26.7]


def test_load_sample_location_filter():
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    with engine.begin() as c:
        n = load.load_sample(c, SAMPLE_CSV, STATIONS_JSON, location_ids={4588})
        assert n == sum(1 for r in _csv_rows() if r["location_id"] == "4588")
        assert c.execute(sa.select(db.stations.c.id)).scalars().all() == [4588]


# --- labels ---------------------------------------------------------------------------------------

def test_qa_eval_07_labels_independent():
    tree = ast.parse(LABELS_PY.read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported.append(mod)
            imported += [f"{mod}.{a.name}" for a in node.names]
    assert imported, "expected labels.py to import something"
    assert not [m for m in imported if m == "aqagent.decide" or m.startswith("aqagent.decide.")]


def test_reference_moments_finds_helsinki_smoke():
    moments = labels.reference_moments(sample_readings(4588), HELSINKI_TZ)
    lo, hi = datetime(2026, 8, 24, 5, tzinfo=UTC), datetime(2026, 8, 24, 9, tzinfo=UTC)
    hits = [m for m in moments if m.kind == "positive" and m.source == "pelt" and m.start <= hi and m.end >= lo]
    assert hits, moments
    assert all(m.location_id == 4588 for m in moments)


def test_change_points_equal_pelt_l2():
    """labels uses ruptures' C linear-kernel PELT, which is the l2 cost; pin that it matches Pelt(model='l2')."""
    import math

    import numpy as np
    import ruptures as rpt

    values = [r.value for r in sample_readings(4588)[1500:1900]]
    y = np.log1p(np.array(values)).reshape(-1, 1)
    expected = rpt.Pelt(model="l2", min_size=3, jump=1).fit(y).predict(pen=3 * math.log(len(y)))
    assert labels.change_points(values) == expected
    assert len(expected) > 1


def test_reference_moments_deterministic():
    rs = sample_readings(4588)
    assert labels.reference_moments(rs, HELSINKI_TZ) == labels.reference_moments(rs, HELSINKI_TZ)


def test_load_hand_labels_helsinki_positive():
    hand = labels.load_hand_labels(LABELS_YAML)
    smoke = [m for m in hand if m.location_id == 4588]
    assert len(smoke) == 1
    m = smoke[0]
    assert (m.kind, m.source) == ("positive", "hand")
    assert (m.start, m.end) == (datetime(2026, 8, 24, 5, tzinfo=UTC), datetime(2026, 8, 24, 9, tzinfo=UTC))


def test_mumbai_glitches_are_hand_negatives():
    rows = sorted((r for r in _csv_rows() if r["location_id"] == "8039"), key=lambda r: r["period_end_utc"])
    values = [float(r["value_ugm3"]) for r in rows]
    glitches = {
        datetime.fromisoformat(rows[i]["period_end_utc"].replace("Z", "+00:00"))
        for i in range(1, len(rows) - 1)
        if values[i] > 3 * max(values[i - 1], 1) and values[i] > 3 * max(values[i + 1], 1)
        and values[i] - values[i - 1] > 20
    }
    assert glitches
    negatives = [m for m in labels.load_hand_labels(LABELS_YAML) if m.location_id == 8039]
    assert all((m.kind, m.source) == ("negative", "hand") for m in negatives)
    assert all(m.start == m.end for m in negatives)
    assert {m.start for m in negatives} == glitches
    assert len(negatives) == len(glitches)


def test_all_moments_merges_pelt_and_hand(loaded):
    conn, _ = loaded
    from_db = labels.all_moments(conn, LABELS_YAML)
    assert set(from_db) == load.TRACKED | load.FIXTURES
    helsinki = from_db[4588]
    assert {m.source for m in helsinki} == {"pelt", "hand"}
    assert helsinki == sorted(helsinki, key=lambda m: (m.start, m.end, m.kind, m.source))
    assert any(m.kind == "negative" for m in from_db[8039])
    by_loc = {loc: sample_readings(loc) for loc in load.TRACKED | load.FIXTURES}
    assert labels.all_moments(by_loc, LABELS_YAML) == from_db
