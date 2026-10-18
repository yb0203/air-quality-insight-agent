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
    assert len(scenarios) == 5
    for s in scenarios:
        r = client.get("/", params={"scenario": s.id})
        assert r.status_code == 200, s.id
