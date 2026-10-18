"""The shipped fixtures are generated from the real replay: every scenario must render."""
from pathlib import Path

from fastapi.testclient import TestClient

from watch_demo.app import create_app
from watch_demo.client import FixtureAgentClient
from watch_demo.scenarios import load_scenarios

ROOT = Path(__file__).resolve().parents[1]


def test_every_real_scenario_renders():
    scenarios = load_scenarios(ROOT / "scenarios.yaml")
    client = TestClient(create_app(FixtureAgentClient(ROOT / "fixtures"), scenarios))
    assert len(scenarios) >= 5
    for s in scenarios:
        r = client.get("/", params={"scenario": s.id})
        assert r.status_code == 200, s.id


def test_scenarios_open_on_their_first_beat_with_story_and_layer_path():
    scenarios = load_scenarios(ROOT / "scenarios.yaml")
    client = TestClient(create_app(FixtureAgentClient(ROOT / "fixtures"), scenarios))
    for s in scenarios:
        html = client.get("/", params={"scenario": s.id}).text
        assert s.question and s.question in html.replace("&#39;", "'")
        assert s.beats, s.id
        assert 'class="beat current"' in html, s.id  # opens on beat 1
        assert html.index('class="story"') < html.index('class="stage"'), "story card sits above the stage"
        assert 'class="path"' in html, f"{s.id}: the moment panel shows the layer path from the real trace"


def test_beat_links_move_the_watch():
    scenarios = load_scenarios(ROOT / "scenarios.yaml")
    client = TestClient(create_app(FixtureAgentClient(ROOT / "fixtures"), scenarios))
    smog = next(s for s in scenarios if s.id == "delhi-smog-night")
    held = client.get("/", params={"scenario": smog.id}).text
    assert "Quiet hours" in held and "QUIET_HOURS_HELD" in held
    check_in = next(b for b in smog.beats if b.title == "One check-in")
    sent = client.get("/", params={"scenario": smog.id, "t": check_in.at.isoformat()}).text
    assert 'class="card' in sent and "SENT_CHECK_IN" in sent


def test_every_beat_is_a_real_decision():
    """Beats are only allowed where the replay actually decided something (the exporter enforces it too)."""
    import json
    from datetime import datetime

    for s in load_scenarios(ROOT / "scenarios.yaml"):
        rows = json.loads((ROOT / "fixtures" / "decisions" / f"{s.user_id}__{s.replay_run}.json").read_text())
        made = {datetime.fromisoformat(r["evaluated_at"].replace("Z", "+00:00")) for r in rows}
        notices = json.loads((ROOT / "fixtures" / "feeds" / f"{s.user_id}__{s.replay_run}.json").read_text())
        made |= {datetime.fromisoformat(str(n["delivered_at"]).replace("Z", "+00:00")) for n in notices}
        for b in s.beats:
            assert b.at in made, f"{s.id}: beat {b.title!r} at {b.at} has no decision"


def test_groups_cover_the_plan():
    groups = {s.group for s in load_scenarios(ROOT / "scenarios.yaml")}
    assert {"speaks", "quiet", "bad-data", "per-person"} <= groups
