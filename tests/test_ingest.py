"""S1 INGEST: OpenAQ v3 client and ingestion runs, against an OpenAQ-shaped httpx.MockTransport."""
import logging
import re
from datetime import datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from aqagent import db, repo
from aqagent.clock import FixedClock
from aqagent.sense.ingest import run_ingestion
from aqagent.sense.openaq import MissingAPIKey, OpenAQClient
from tests.fixtures import UTC, hourly

NOW = datetime(2026, 10, 18, 9, 20, tzinfo=UTC)
H = timedelta(hours=1)
KEY = "test-key-not-a-secret-7f3a"
SENSORS = {11382: (4588, "Helsinki"), 25196: (7936, "Los Angeles"), 15203555: (6206921, "Bengaluru"),
           14384841: (6096447, "Dubai"), 15289075: (4712609, "Delhi")}


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class FakeOpenAQ:
    """Serves /v3/sensors/{id}/hours from in-memory series, with paging, failures and rate-limit headers."""

    def __init__(self):
        self.series: dict[int, dict[datetime, tuple[float | None, float | None]]] = {}
        self.fail: dict[int, int] = {}  # sensor -> HTTP status, every time
        self.queue: dict[int, list[httpx.Response]] = {}  # sensor -> canned responses served first
        self.requests: list[httpx.Request] = []
        self.remaining = 55

    def put(self, sensor_id, first_end, values, coverage=100.0):
        s = self.series.setdefault(sensor_id, {})
        for i, v in enumerate(values):
            if v is not None:
                s[first_end + i * H] = (float(v), coverage)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        m = re.fullmatch(r"/v3/sensors/(\d+)/hours", request.url.path)
        assert m, request.url.path
        sid = int(m[1])
        if self.queue.get(sid):
            return self.queue[sid].pop(0)
        if sid in self.fail:
            return httpx.Response(self.fail[sid], json={"detail": "nope"})
        q = request.url.params
        lo, hi, limit, page = _parse(q["datetime_from"]), _parse(q["datetime_to"]), int(q["limit"]), int(q["page"])
        ends = sorted(e for e in self.series.get(sid, {}) if lo < e <= hi)
        chunk = ends[(page - 1) * limit: page * limit]
        results = [{"value": self.series[sid][e][0],
                    "period": {"label": "1hour", "interval": "01:00:00",
                               "datetimeFrom": {"utc": _iso(e - H), "local": "x"},
                               "datetimeTo": {"utc": _iso(e), "local": "x"}},
                    "coverage": {"expectedCount": 1, "observedCount": 1, "percentComplete": 100.0,
                                 "percentCoverage": self.series[sid][e][1]},
                    "summary": {}, "flagInfo": {"hasFlags": False}} for e in chunk]
        return httpx.Response(200, headers={"x-ratelimit-remaining": str(self.remaining),
                                            "x-ratelimit-reset": "30"},
                              json={"meta": {"name": "openaq-api", "page": page, "limit": limit,
                                             "found": len(ends)}, "results": results})

    def hour_requests(self, sensor_id=None):
        return [r for r in self.requests
                if sensor_id is None or r.url.path == f"/v3/sensors/{sensor_id}/hours"]


@pytest.fixture
def env():
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    fake = FakeOpenAQ()
    sleeps: list[float] = []
    client = OpenAQClient(KEY, transport=httpx.MockTransport(fake.handler), sleep=sleeps.append)
    with engine.begin() as conn:
        for sid, (loc, city) in SENSORS.items():
            repo.upsert_station(conn, id=loc, city=city, name=city, provider="test", timezone="UTC",
                                is_reference=False)
            repo.upsert_sensor(conn, id=sid, station_id=loc, parameter="pm25", units="µg/m³")
        yield conn, fake, client, FixedClock(NOW), sleeps


def _seed_recent(conn, sensor_ids):
    """A stored hour 2 h ago, so the next run is a trailing-window ('hourly') run, not a backfill."""
    for sid in sensor_ids:
        repo.upsert_readings(conn, hourly(NOW - 2 * H, [5.0], sensor_id=sid), ingested_at=NOW - H, run_id=None)


def _runs(conn):
    return list(conn.execute(sa.select(db.ingestion_runs).order_by(db.ingestion_runs.c.id)))


def _versions(conn, sid, end):
    return conn.execute(sa.select(sa.func.count()).select_from(db.readings).where(
        db.readings.c.sensor_id == sid, db.readings.c.period_end == end)).scalar()


def test_qa_ing_01_trailing_window(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, SENSORS)
    for sid in SENSORS:
        fake.put(sid, NOW - 24 * H + timedelta(minutes=40), [10 + i for i in range(24)])
    report = run_ingestion(conn, client, clock, list(SENSORS))
    reqs = fake.hour_requests()
    assert len(reqs) == 5
    assert {r.url.path for r in reqs} == {f"/v3/sensors/{sid}/hours" for sid in SENSORS}
    for r in reqs:
        assert _parse(r.url.params["datetime_from"]) == NOW - 24 * H
        assert _parse(r.url.params["datetime_to"]) == NOW
        assert r.headers["X-API-Key"] == KEY
    assert {row.kind for row in _runs(conn)} == {"hourly"}
    assert report.new == 5 * 24 and report.status == "ok"
    for sid in SENSORS:
        assert len(repo.readings_as_of(conn, sid, NOW - 25 * H, NOW, as_of=NOW)) == 24 + 1


def test_qa_ing_02_idempotent(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, SENSORS)
    fake.put(11382, NOW - 10 * H, [5, 6, 7, 8])
    first = run_ingestion(conn, client, clock, [11382])
    assert (first.new, first.revised) == (4, 0)
    clock.advance(H)
    second = run_ingestion(conn, client, clock, [11382])
    assert (second.new, second.revised) == (0, 0) and second.changed == {}
    assert conn.execute(sa.select(sa.func.count()).select_from(db.readings)
                        .where(db.readings.c.sensor_id == 11382)).scalar() == 5


def test_qa_ing_03_revision_kept(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, [11382])
    hour = NOW - 5 * H + timedelta(minutes=40)
    fake.put(11382, hour, [40])
    run_ingestion(conn, client, clock, [11382])
    fake.put(11382, hour, [55])
    clock.advance(H)
    report = run_ingestion(conn, client, clock, [11382])
    assert (report.new, report.revised) == (0, 1) and report.changed == {11382: [hour]}
    assert _versions(conn, 11382, hour) == 2
    [before] = repo.readings_as_of(conn, 11382, hour, hour, as_of=NOW)
    [after] = repo.readings_as_of(conn, 11382, hour, hour, as_of=clock.now())
    assert (before.value, after.value) == (40, 55)


def test_qa_ing_04_gaps_not_interpolated(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, [11382])
    first = NOW - 12 * H + timedelta(minutes=40)
    fake.put(11382, first, [10, 11, None, None, None, 15, 16])
    report = run_ingestion(conn, client, clock, [11382])
    assert report.new == 4
    for i in (2, 3, 4):
        assert _versions(conn, 11382, first + i * H) == 0
    got = repo.readings_as_of(conn, 11382, first, first + 6 * H, as_of=NOW)
    assert [r.period_end for r in got] == [first + i * H for i in (0, 1, 5, 6)]


def test_qa_ing_06_backfill(env):
    conn, fake, client, clock, _ = env
    first = NOW - timedelta(days=90) + timedelta(minutes=40)
    fake.put(11382, first, [7.0] * (90 * 24))
    report = run_ingestion(conn, client, clock, [11382])
    reqs = fake.hour_requests(11382)
    assert _parse(reqs[0].url.params["datetime_from"]) == NOW - timedelta(days=90)
    assert [r.url.params["page"] for r in reqs] == ["1", "2", "3"]
    assert all(r.url.params["limit"] == "1000" for r in reqs)
    [run] = _runs(conn)
    assert run.kind == "backfill" and run.status == "ok" and run.rows_fetched == 2160
    assert report.new == 2160 and len(report.changed[11382]) == 2160


def test_qa_ing_06_stale_sensor_backfills_from_its_newest_hour(env):
    conn, fake, client, clock, _ = env
    stale = NOW - 50 * H
    repo.upsert_readings(conn, hourly(stale, [5.0], sensor_id=11382), ingested_at=stale + H, run_id=None)
    run_ingestion(conn, client, clock, [11382])
    [req] = fake.hour_requests(11382)
    assert _parse(req.url.params["datetime_from"]) == stale - 24 * H
    assert _runs(conn)[0].kind == "backfill"


def test_qa_ing_07_partial_failure(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, SENSORS)
    for sid in SENSORS:
        fake.put(sid, NOW - 6 * H, [20, 21, 22])
    bad = 15203555
    fake.fail[bad] = 500
    report = run_ingestion(conn, client, clock, list(SENSORS))
    assert report.status == "partial" and set(report.errors) == {bad}
    statuses = {row.sensor_id: row.status for row in _runs(conn)}
    assert statuses[bad] == "error" and all(s == "ok" for sid, s in statuses.items() if sid != bad)
    assert "500" in next(r.error for r in _runs(conn) if r.sensor_id == bad)
    assert bad not in report.changed and len(report.changed) == 4

    del fake.fail[bad]
    clock.advance(H)
    report2 = run_ingestion(conn, client, clock, list(SENSORS))
    assert report2.status == "ok"
    assert report2.changed == {bad: [NOW - 6 * H, NOW - 5 * H, NOW - 4 * H]}


def test_qa_ing_08_rate_limit_backoff(env):
    conn, fake, client, clock, sleeps = env
    _seed_recent(conn, [11382])
    fake.put(11382, NOW - 3 * H, [9])
    fake.queue[11382] = [httpx.Response(429, headers={"x-ratelimit-reset": "7", "x-ratelimit-remaining": "0"})]
    report = run_ingestion(conn, client, clock, [11382])
    assert sleeps == [7.0]
    assert len(fake.hour_requests(11382)) == 2
    [run] = _runs(conn)
    assert run.status == "ok" and run.ratelimit_remaining == 55 and report.new == 1
    assert client.last_ratelimit_remaining == 55


def test_qa_ing_08_rate_limit_gives_up_after_three_tries(env):
    conn, fake, client, clock, sleeps = env
    _seed_recent(conn, [11382])
    fake.queue[11382] = [httpx.Response(429, headers={"x-ratelimit-reset": "3"}) for _ in range(5)]
    report = run_ingestion(conn, client, clock, [11382])
    assert len(fake.hour_requests(11382)) == 3
    assert sleeps == [3.0, 3.0]  # sleeps between tries, never a tight retry
    assert report.status == "error" and "429" in _runs(conn)[0].error


def test_qa_ing_08_pauses_when_remaining_hits_zero(env):
    conn, fake, client, clock, sleeps = env
    _seed_recent(conn, [11382, 25196])
    fake.remaining = 0
    run_ingestion(conn, client, clock, [11382, 25196])
    assert sleeps == [30.0]  # waited for the reset before the second call, not after the last one
    assert [r.ratelimit_remaining for r in _runs(conn)] == [0, 0]


def test_qa_ing_09_half_hour_periods(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, [15289075])
    end = datetime(2026, 10, 18, 5, 30, tzinfo=UTC)
    fake.put(15289075, end, [88.0])
    report = run_ingestion(conn, client, clock, [15289075])
    assert report.changed == {15289075: [end]}
    [got] = repo.readings_as_of(conn, 15289075, end, end, as_of=NOW)
    assert got.period_end == end and got.period_start == end - H and got.coverage_pct == 100.0


def test_qa_ing_12_missing_key(env, caplog, monkeypatch):
    for bad in ("", "   ", None):
        with pytest.raises(MissingAPIKey):
            OpenAQClient(bad)
    conn, fake, client, clock, _ = env
    caplog.set_level(logging.DEBUG)
    _seed_recent(conn, SENSORS)
    fake.put(11382, NOW - 3 * H, [9])
    fake.fail[25196] = 500
    fake.fail[14384841] = 401
    run_ingestion(conn, client, clock, list(SENSORS))
    assert fake.requests and all(r.headers["X-API-Key"] == KEY for r in fake.requests)
    assert caplog.records, "expected some logging to check"
    assert KEY not in caplog.text
    assert all(KEY not in (r.error or "") for r in _runs(conn))
    assert KEY not in repr(client)


def test_qa_ing_13_run_row(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, [11382])
    fake.put(11382, NOW - 4 * H, [5.0, 6.0, 7.0])
    fake.put(11382, NOW - 2 * H, [6.5])  # a revision of the seeded hour
    run_ingestion(conn, client, clock, [11382])
    [run] = _runs(conn)
    assert run.started_at == NOW and run.finished_at == NOW
    assert (run.window_from, run.window_to) == (NOW - 24 * H, NOW)
    assert (run.rows_fetched, run.rows_new, run.rows_revised) == (3, 2, 1)
    assert run.newest_period_end == NOW - 2 * H
    assert run.status == "ok" and run.error is None and run.ratelimit_remaining == 55
    assert run.sensor_id == 11382 and run.kind == "hourly"
    # readings point at the run that stored them
    run_ids = {r.run_id for r in conn.execute(sa.select(db.readings.c.run_id)
                                              .where(db.readings.c.ingested_at == NOW))}
    assert run_ids == {run.id}


def test_review_sensor_404_is_partial(env):
    conn, fake, client, clock, _ = env
    _seed_recent(conn, SENSORS)
    for sid in SENSORS:
        fake.put(sid, NOW - 4 * H, [30, 31])
    gone, empty = 11382, 25196
    fake.fail[gone] = 404
    fake.series.pop(empty)  # 200 with empty results
    report = run_ingestion(conn, client, clock, list(SENSORS))  # must not raise
    runs = {r.sensor_id: r for r in _runs(conn)}
    assert runs[gone].status == "error" and "404" in runs[gone].error
    assert runs[empty].status == "ok" and runs[empty].rows_fetched == 0
    # freshness still reported from what we hold, so the stale sensor ages towards NO_DATA
    assert runs[gone].newest_period_end == NOW - 2 * H and runs[empty].newest_period_end == NOW - 2 * H
    assert report.status == "partial" and set(report.errors) == {gone}
    assert set(report.changed) == set(SENSORS) - {gone, empty}
    for sid in set(SENSORS) - {gone, empty}:
        assert runs[sid].status == "ok" and runs[sid].rows_new == 2
