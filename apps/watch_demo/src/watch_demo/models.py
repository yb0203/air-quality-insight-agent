"""Shapes of the core API's JSON, as the watch demo reads them.

Unknown fields are ignored so the core can grow its payloads without
breaking the demo. Fields the demo can live without are optional.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Band = Literal["good", "moderate", "usg", "unhealthy", "very_unhealthy", "hazardous"]
Kind = Literal["opened", "escalated", "cleared", "check_in", "released"]
EventKind = Literal["spike", "climb", "elevated", "floor"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class User(_Model):
    id: str
    display_name: str
    city: str
    station_id: int
    persona: Any = None
    # Not in the agreed contract yet; the demo falls back to a city lookup.
    timezone: str | None = None


class Notification(_Model):
    id: str
    created_at: datetime
    delivered_at: datetime | None = None
    kind: Kind
    event_kind: EventKind | None = None
    band: Band
    body: str
    next_action: str
    decision_id: str

    @property
    def shown_at(self) -> datetime:
        return self.delivered_at or self.created_at


class TraceEntry(_Model):
    layer: str
    passed: bool
    reason_code: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class Decision(_Model):
    id: str | None = None
    evaluated_at: datetime
    # The reading hour the decision is about; clock-triggered decisions may not have one.
    period_end: datetime | None = None
    outcome: Literal["sent", "held", "suppressed", "no_event"]
    reason_code: str
    reason: str = ""
    trigger: str | None = None
    # Layer-by-layer trace, when the source provides it (fixtures do; the API's /decisions doesn't yet).
    trace: list[TraceEntry] = Field(default_factory=list)

    @property
    def about(self) -> datetime:
        return self.period_end or self.evaluated_at


class Reading(_Model):
    at: datetime
    pm25: float | None = None
    nowcast: float | None = None
    band: Band | None = None
    typical_pm25: float | None = None
    # Data-quality code when the agent excluded this hour (e.g. DQ_SUSPECT).
    dq: str | None = None


class Explain(_Model):
    decision: Decision
    trace: list[TraceEntry] = Field(default_factory=list)
    scores: list[dict[str, Any]] = Field(default_factory=list)
    rules_version: int | str | None = None

    def layer(self, name: str) -> TraceEntry | None:
        return next((t for t in self.trace if t.layer == name), None)
