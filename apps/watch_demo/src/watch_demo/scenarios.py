"""Demo scenarios: which person, which replay run, and the replayed 'now'."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel


class Scenario(BaseModel):
    id: str
    label: str
    user_id: str
    replay_run: str
    until: datetime
    description: str
    limit: int | None = None
    chart_hours: int = 24


def default_scenarios_path() -> Path:
    return Path(os.environ.get("WATCH_DEMO_SCENARIOS", Path(__file__).resolve().parents[2] / "scenarios.yaml"))


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    data = yaml.safe_load((path or default_scenarios_path()).read_text())
    return [Scenario.model_validate(s) for s in data["scenarios"]]
