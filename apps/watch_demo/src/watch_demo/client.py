"""Read the agent's notifications: from the core API over HTTP, or from fixtures.

The watch demo never imports the core library. With `AQAGENT_API_URL` set it
talks to the running core; without it, it reads JSON files that follow the
same contract, so the demo works offline.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from .models import Decision, Explain, Notification, User


class AgentClient(Protocol):
    def users(self) -> list[User]: ...

    def feed(self, user_id: str, replay_run: str, until: datetime) -> list[Notification]: ...

    def explain(self, notification_id: str) -> Explain: ...

    def decisions(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
        outcome: str | None = None,
        replay_run: str | None = None,
    ) -> list[Decision]: ...


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


class HttpAgentClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0, transport=transport)

    def _get(self, path: str, **params: str) -> object:
        resp = self._http.get(path, params={k: v for k, v in params.items() if v is not None})
        resp.raise_for_status()
        return resp.json()

    def users(self) -> list[User]:
        return [User.model_validate(u) for u in self._get("/users")]

    def feed(self, user_id: str, replay_run: str, until: datetime) -> list[Notification]:
        rows = self._get(f"/users/{user_id}/feed", replay_run=replay_run, until=_iso(until))
        return [Notification.model_validate(n) for n in rows]

    def explain(self, notification_id: str) -> Explain:
        return Explain.model_validate(self._get(f"/notifications/{notification_id}/explain"))

    def decisions(self, user_id, start, end, outcome=None, replay_run=None) -> list[Decision]:
        rows = self._get(
            "/decisions",
            user_id=user_id,
            start=_iso(start),
            end=_iso(end),
            outcome=outcome,
            replay_run=replay_run,
        )
        return [Decision.model_validate(d) for d in rows]


class FixtureAgentClient:
    """Serves contract-shaped JSON from disk, applying the same filters the API does.

    Layout:
      users.json
      feeds/<user_id>__<replay_run>.json        whole feed; filtered by `until` here
      decisions/<user_id>__<replay_run>.json    filtered by start/end/outcome here
      explain/<notification_id>.json
    """

    def __init__(self, root: Path):
        self.root = root

    def _load(self, *parts: str) -> object:
        path = self.root.joinpath(*parts)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def users(self) -> list[User]:
        return [User.model_validate(u) for u in self._load("users.json") or []]

    def feed(self, user_id: str, replay_run: str, until: datetime) -> list[Notification]:
        rows = self._load("feeds", f"{user_id}__{replay_run}.json") or []
        items = [Notification.model_validate(n) for n in rows]
        items = [n for n in items if n.shown_at <= until]
        return sorted(items, key=lambda n: n.shown_at, reverse=True)

    def explain(self, notification_id: str) -> Explain:
        data = self._load("explain", f"{notification_id}.json")
        if data is None:
            raise KeyError(notification_id)
        return Explain.model_validate(data)

    def decisions(self, user_id, start, end, outcome=None, replay_run=None) -> list[Decision]:
        rows = self._load("decisions", f"{user_id}__{replay_run}.json") or []
        items = [Decision.model_validate(d) for d in rows]
        return [
            d
            for d in items
            if start <= d.evaluated_at <= end and (outcome is None or d.outcome == outcome)
        ]


def default_fixtures_dir() -> Path:
    return Path(os.environ.get("WATCH_DEMO_FIXTURES", Path(__file__).resolve().parents[2] / "fixtures"))


def client_from_env() -> AgentClient:
    url = os.environ.get("AQAGENT_API_URL")
    if url:
        return HttpAgentClient(url)
    return FixtureAgentClient(default_fixtures_dir())
