"""Read side of the API (QA-OBS-03..06, QA-FB-01/02) over an in-memory SQLite DB built with direct inserts."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aqagent import db
from aqagent.api import create_app
from aqagent.clock import FixedClock
from aqagent.learn import feedback
from aqagent.repo import upsert_readings
from tests.fixtures import hourly

UTC = timezone.utc
HOUR = timedelta(hours=1)
T = datetime(2026, 10, 10, 6, tzinfo=UTC)  # the hour of the sent notice
NOW = datetime(2026, 10, 12, 9, tzinfo=UTC)
SENSOR = 11
TRACE = [{"layer": "S2/U2", "passed": True, "reason_code": None, "inputs": {}, "values": {"z": 4.1}},
         {"layer": "D1", "passed": True, "reason_code": None, "inputs": {}, "values": {"label": "spike"}}]
FEED_KEYS = {"id", "created_at", "delivered_at", "kind", "event_kind", "band", "body", "next_action", "decision_id"}
DECISION_KEYS = {"id", "evaluated_at", "period_end", "user_id", "outcome", "reason_code", "reason", "trigger"}


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.fixture
def engine():
    eng = db.make_engine("sqlite://")
    db.create_all(eng)
    return eng


@pytest.fixture
def seeded(engine):
    """aino in Helsinki: one sent decision with a delivered notice, one suppressed, one held (its notice not yet
    delivered), and a replay-tagged sent decision with its own delivered notice."""
    ids = {}
    with engine.begin() as c:
        c.execute(db.stations.insert().values(id=1, city="Helsinki", name="Kallio 2", provider="HSY",
                                              is_reference=True, timezone="Europe/Helsinki"))
        c.execute(db.sensors.insert().values(id=SENSOR, station_id=1, parameter="pm25", units="µg/m³"))
        c.execute(db.users.insert().values(id="aino", display_name="Aino", station_id=1,
                                           persona={"conditions": ["asthma"]}, city="Helsinki"))
        c.execute(db.user_rules.insert().values(user_id="aino", version=1, source="default",
                                                rules={"sensitivity": "default"}, created_at=T - 30 * 24 * HOUR))
        # readings: 30 hours ending at T, first known at period_end + 10 min; then T is revised after evaluation
        upsert_readings(c, hourly(T - 29 * HOUR, [10.0] * 29 + [55.0], sensor_id=SENSOR),
                        ingested_at=T + timedelta(minutes=10), run_id=None)
        upsert_readings(c, hourly(T, [99.0], sensor_id=SENSOR), ingested_at=T + 5 * HOUR, run_id=None)
        old_b = c.execute(db.baselines.insert().values(
            sensor_id=SENSOR, fitted_at=T - 24 * HOUR, trained_through=T - 25 * HOUR, model="hod_robust",
            params={"median": [10.0] * 24})).inserted_primary_key[0]
        c.execute(db.baselines.insert().values(
            sensor_id=SENSOR, fitted_at=T + 24 * HOUR, trained_through=T + 23 * HOUR, model="hod_robust",
            params={"median": [11.0] * 24}))
        ids["baseline"] = old_b
        score_ids = []
        for i, end in enumerate([T - 2 * HOUR, T - HOUR, T]):
            score_ids.append(c.execute(db.station_scores.insert().values(
                sensor_id=SENSOR, period_end=end, evaluated_at=T + timedelta(minutes=20), baseline_id=old_b,
                z=float(i), ewma=0.5 * i, band="usg", typical_band="moderate", evidence={"i": i},
            )).inserted_primary_key[0])
        # a score row that isn't behind the decision
        c.execute(db.station_scores.insert().values(
            sensor_id=SENSOR, period_end=T + HOUR, evaluated_at=T + timedelta(hours=1, minutes=20), evidence={}))
        ids["score_ids"] = score_ids

        def decision(period_end, outcome, code, reason, replay_run=None, trigger="data"):
            return c.execute(db.decisions.insert().values(
                evaluated_at=period_end + timedelta(minutes=20), period_end=period_end, user_id="aino",
                sensor_id=SENSOR, rules_version=1, score_ids=score_ids if outcome == "sent" else None,
                outcome=outcome, reason_code=code, reason=reason, trigger=trigger, trace=TRACE,
                replay_run=replay_run)).inserted_primary_key[0]

        ids["sent"] = decision(T, "sent", "SENT_OPENED", "Sent: air quality turned bad.")
        ids["suppressed"] = decision(T + HOUR, "suppressed", "COOLDOWN", "Too soon after the last message about this.")
        ids["held"] = decision(T + 18 * HOUR, "held", "QUIET_HOURS_HELD", "Held until quiet hours end.")
        ids["replay"] = decision(T + 2 * HOUR, "sent", "SENT_ESCALATED", "Sent: it got a full band worse.",
                                 replay_run="r1")

        def notice(decision_id, created, delivered, body, facts):
            return c.execute(db.notifications.insert().values(
                decision_id=decision_id, user_id="aino", created_at=created, deliver_after=created,
                delivered_at=delivered, kind="opened", body=body, next_action="Keep windows shut tonight.",
                context_facts=facts, generator="template")).inserted_primary_key[0]

        sent_at = T + timedelta(minutes=21)
        ids["n_sent"] = notice(ids["sent"], sent_at, sent_at, "PM2.5 is well above normal for Kallio this morning.",
                               {"event_kind": "spike", "now": {"band": "usg", "pm25": 55}})
        ids["n_held"] = notice(ids["held"], T + 18 * HOUR, None, "Held overnight.", {})
        replay_at = T + timedelta(hours=2, minutes=21)
        ids["n_replay"] = notice(ids["replay"], replay_at, replay_at, "Replay: it got worse.",
                                 {"event_kind": "climb", "now": {"band": "unhealthy"}})
    return ids


@pytest.fixture
def clock():
    return FixedClock(NOW)


@pytest.fixture
def client(engine, clock):
    return TestClient(create_app(engine, clock))


def test_health_empty_db(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sensors": []}


def test_health_reports_sensor_age(client, seeded):
    body = client.get("/health").json()
    assert body["ok"] is True
    [s] = body["sensors"]
    assert s["sensor_id"] == SENSOR and s["city"] == "Helsinki"
    assert parse(s["newest_reading_at"]) == T
    assert s["age_hours"] == pytest.approx((NOW - T).total_seconds() / 3600)


def test_users_list(client, seeded):
    assert client.get("/users").json() == [{"id": "aino", "display_name": "Aino", "city": "Helsinki",
                                            "station_id": 1, "persona": {"conditions": ["asthma"]}}]


def test_feed_contract_shape(client, seeded):
    r = client.get("/users/aino/feed")
    assert r.status_code == 200
    [item] = r.json()  # the held notice isn't delivered; the replay one isn't live
    assert set(item) == FEED_KEYS
    assert item["id"] == seeded["n_sent"] and item["decision_id"] == seeded["sent"]
    assert (item["kind"], item["event_kind"], item["band"]) == ("opened", "spike", "usg")
    assert item["next_action"] == "Keep windows shut tonight."
    assert parse(item["created_at"]) == T + timedelta(minutes=21)
    assert parse(item["delivered_at"]).utcoffset() == timedelta(0)


def test_feed_until_and_missing_facts(client, seeded, engine):
    with engine.begin() as c:  # a later live notice with no event_kind/band in its facts
        later = T + timedelta(hours=30)
        nid = c.execute(db.notifications.insert().values(
            decision_id=seeded["held"], user_id="aino", created_at=later, deliver_after=later, delivered_at=later,
            kind="released_after_quiet_hours", body="Released.", next_action="Check again at noon.",
            context_facts={}, generator="template")).inserted_primary_key[0]
    items = client.get("/users/aino/feed").json()
    assert [i["id"] for i in items] == [nid, seeded["n_sent"]]  # newest first
    assert items[0]["event_kind"] is None and items[0]["band"] is None
    until = (T + timedelta(hours=1)).isoformat()
    assert [i["id"] for i in client.get("/users/aino/feed", params={"until": until}).json()] == [seeded["n_sent"]]


def test_feed_and_export_unknown_user_404(client, seeded):
    assert client.get("/users/nobody/feed").status_code == 404
    assert client.get("/users/nobody/export").status_code == 404


def test_qa_obs_03_explain(client, seeded):
    r = client.get(f"/notifications/{seeded['n_sent']}/explain")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"decision", "trace", "scores", "readings", "baseline", "rules_version"}
    assert set(body["decision"]) == {"outcome", "reason_code", "reason", "evaluated_at", "trigger"}
    assert body["decision"]["outcome"] == "sent" and body["decision"]["reason_code"] == "SENT_OPENED"
    assert body["decision"]["trigger"] == "data"
    evaluated_at = parse(body["decision"]["evaluated_at"])
    assert evaluated_at == T + timedelta(minutes=20)
    assert body["trace"] == TRACE
    assert [s["id"] for s in body["scores"]] == seeded["score_ids"]
    assert body["scores"][-1]["band"] == "usg" and body["scores"][-1]["evidence"] == {"i": 2}
    # readings as known at evaluated_at: the 24 h up to period_end, without the later revision of T to 99
    readings = body["readings"]
    assert len(readings) == 24
    assert parse(readings[0]["period_end"]) == T - 23 * HOUR and parse(readings[-1]["period_end"]) == T
    assert readings[-1]["value"] == 55.0
    # the newest baseline fitted at or before evaluated_at, not the later refit
    assert body["baseline"]["id"] == seeded["baseline"] and body["baseline"]["model"] == "hod_robust"
    assert parse(body["baseline"]["fitted_at"]) <= evaluated_at
    assert body["rules_version"] == 1


def test_explain_without_scores_or_baseline(client, engine, seeded):
    with engine.begin() as c:  # every baseline now postdates the held decision
        c.execute(db.baselines.update().values(fitted_at=NOW))
    body = client.get(f"/notifications/{seeded['n_held']}/explain").json()
    assert body["scores"] == [] and body["baseline"] is None
    assert body["decision"]["outcome"] == "held"


def test_qa_obs_04_missing_nudge_query(client, seeded):
    params = {"user_id": "aino", "start": (T - HOUR).isoformat(), "end": (T + 20 * HOUR).isoformat()}
    rows = client.get("/decisions", params=params).json()
    assert all(set(r) == DECISION_KEYS for r in rows)
    by_outcome = {r["outcome"]: r for r in rows}
    assert set(by_outcome) == {"sent", "suppressed", "held"}  # the replay row is not live
    sup = by_outcome["suppressed"]
    assert sup["id"] == seeded["suppressed"] and sup["reason_code"] == "COOLDOWN"
    assert sup["reason"] == "Too soon after the last message about this."
    assert parse(sup["period_end"]) == T + HOUR and sup["trigger"] == "data"
    only = client.get("/decisions", params={**params, "outcome": "suppressed"}).json()
    assert [r["id"] for r in only] == [seeded["suppressed"]]
    narrow = client.get("/decisions", params={"user_id": "aino", "start": (T + HOUR).isoformat(),
                                              "end": (T + HOUR).isoformat()}).json()
    assert [r["id"] for r in narrow] == [seeded["suppressed"]]
    assert client.get("/decisions", params={"user_id": "nobody"}).json() == []


def test_qa_obs_05_export(client, seeded):
    r = client.get("/users/aino/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["delivered_at", "kind", "body", "next_action", "decision_id"]
    assert len(rows) == 2  # one delivered live notice
    assert parse(rows[1][0]) == T + timedelta(minutes=21)
    assert rows[1][1:] == ["opened", "PM2.5 is well above normal for Kallio this morning.",
                           "Keep windows shut tonight.", str(seeded["sent"])]
    replay = list(csv.reader(io.StringIO(client.get("/users/aino/export", params={"replay_run": "r1"}).text)))
    assert [row[4] for row in replay[1:]] == [str(seeded["replay"])]


def test_qa_obs_06_live_excludes_replay(client, seeded):
    live = client.get("/users/aino/feed").json()
    assert seeded["n_replay"] not in [i["id"] for i in live]
    replay = client.get("/users/aino/feed", params={"replay_run": "r1"}).json()
    assert [i["id"] for i in replay] == [seeded["n_replay"]]
    assert (replay[0]["event_kind"], replay[0]["band"]) == ("climb", "unhealthy")
    assert [r["id"] for r in client.get("/decisions", params={"replay_run": "r1"}).json()] == [seeded["replay"]]
    assert seeded["replay"] not in [r["id"] for r in client.get("/decisions").json()]


def _rules_rows(engine):
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(sa.select(db.user_rules).order_by(db.user_rules.c.id))]


def test_qa_fb_01_feedback_recorded(client, engine, seeded):
    before = _rules_rows(engine)
    r = client.post(f"/notifications/{seeded['n_sent']}/feedback", json={"action": "acted"})
    assert r.status_code == 201
    fid = r.json()["id"]
    with engine.connect() as c:
        row = c.execute(sa.select(db.feedback).where(db.feedback.c.id == fid)).one()
    assert (row.notification_id, row.user_id, row.action, row.at) == (seeded["n_sent"], "aino", "acted", NOW)
    assert _rules_rows(engine) == before


def test_feedback_bad_action_422(client, engine, seeded):
    r = client.post(f"/notifications/{seeded['n_sent']}/feedback", json={"action": "loved_it"})
    assert r.status_code == 422
    with engine.connect() as c:
        assert c.execute(sa.select(sa.func.count()).select_from(db.feedback)).scalar() == 0


def test_qa_fb_02_unknown_404(client, engine, seeded):
    assert client.post("/notifications/9999/feedback", json={"action": "dismissed"}).status_code == 404
    assert client.get("/notifications/9999/explain").status_code == 404
    with engine.begin() as c, pytest.raises(feedback.UnknownNotification):
        feedback.record(c, 9999, "aino", "dismissed", NOW)
