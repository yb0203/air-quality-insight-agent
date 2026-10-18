"""Demo scenarios: which person, which replay run, the replayed 'now', and the story to tell about it."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel


GROUPS = {
    "speaks": "When it speaks",
    "quiet": "When it stays quiet",
    "bad-data": "When data can't be trusted",
    "per-person": "Same air, different person",
}


class Beat(BaseModel):
    """A moment worth stopping at: the cursor jumps here, and the chart pins its number."""

    at: datetime
    title: str
    note: str = ""


class Scenario(BaseModel):
    id: str
    label: str
    user_id: str
    replay_run: str
    until: datetime
    description: str
    limit: int | None = None
    chart_hours: int = 24
    group: str | None = None
    question: str | None = None  # the story's lead, shown above the stage
    shows: list[str] = []  # capability keys, see capabilities.py
    brief: list[str] = []  # brief requirement ids, e.g. B2a
    beats: list[Beat] = []

    @property
    def start(self) -> datetime:
        return self.until - timedelta(hours=self.chart_hours)

    @property
    def opens_at(self) -> datetime:
        """Where the cursor starts: the first beat, else the end of the window."""
        return self.beats[0].at if self.beats else self.until


def default_scenarios_path() -> Path:
    return Path(os.environ.get("WATCH_DEMO_SCENARIOS", Path(__file__).resolve().parents[2] / "scenarios.yaml"))


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    data = yaml.safe_load((path or default_scenarios_path()).read_text())
    return [Scenario.model_validate(s) for s in data["scenarios"]]
