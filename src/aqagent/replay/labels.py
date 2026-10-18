"""Reference labels for the evaluation harness (S-C §12, FR-EVAL-3).

Independent of the decision engine by construction (QA-EVAL-07): nothing here imports `aqagent.decide`,
so the harness grades the agent against moments it had no hand in choosing.

- PELT moments: change points of `y = log1p(PM2.5)` (ruptures, l2 cost, penalty 3·ln n, min segment 3).
  An "interesting moment" is an upward change whose new segment mean (back in µg/m³) is at least one EPA
  band above the previous segment's, or at least twice it, and that lasts at least 3 h.
- Hand labels (data/labels.yaml): known events (positives) and sensor glitches (negatives).

All moment times are UTC `period_end` values (the reading's time).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Literal, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import ruptures as rpt
import sqlalchemy as sa
import yaml
from sqlalchemy.engine import Connection

from aqagent import repo
from aqagent.db import readings as readings_table
from aqagent.db import sensors, stations
from aqagent.types import Reading
from aqagent.understand.aqi import band_for

UTC = timezone.utc
STATIONS_JSON = Path(__file__).resolve().parents[3] / "data" / "samples" / "stations.json"

# S-C §12 labelling constants (evaluation-only; not agent parameters, so not in params.py).
PELT_PENALTY_PER_LOG_N = 3
PELT_MIN_SIZE = 3
MIN_RATIO = 2.0
MIN_BAND_STEP = 1
MIN_DURATION = timedelta(hours=3)


@dataclass(frozen=True)
class Moment:
    location_id: int
    start: datetime
    end: datetime
    kind: Literal["positive", "negative"]
    source: Literal["pelt", "hand"]
    note: str = ""


def _sort_key(m: Moment):
    return (m.start, m.end, m.kind, m.source)


def change_points(values: list[float]) -> list[int]:
    """PELT breakpoints (ruptures convention: segment end indices, the last == len(values)).

    Uses ruptures' C implementation with a linear kernel, which is exactly the l2 cost of
    `Pelt(model="l2")` and about 1000x faster (pinned by `test_change_points_equal_pelt_l2`).
    """
    y = np.log1p(np.clip(np.asarray(values, dtype=float), 0.0, None)).reshape(-1, 1)
    n = len(y)
    if n < 2 * PELT_MIN_SIZE:
        return [n] if n else []
    algo = rpt.KernelCPD(kernel="linear", min_size=PELT_MIN_SIZE, jump=1).fit(y)
    return [int(b) for b in algo.predict(pen=PELT_PENALTY_PER_LOG_N * math.log(n))]


@lru_cache(maxsize=1)
def _sample_stations() -> dict[str, dict[int, object]]:
    """From stations.json: {'location': {sensor_id: location_id}, 'tz': {location_id: timezone name}}."""
    data = json.loads(STATIONS_JSON.read_text()) if STATIONS_JSON.exists() else []
    return {"location": {int(s["pm25_sensor_id"]): int(s["location_id"]) for s in data},
            "tz": {int(s["location_id"]): s["timezone"] for s in data}}


def reference_moments(readings: list[Reading], tz: tzinfo, location_id: int | None = None) -> list[Moment]:
    """Positive PELT moments for one station's readings, ascending by start. Deterministic.

    `tz` is the station's timezone (part of the harness interface; moments themselves are UTC).
    `location_id` defaults to the location of the readings' sensor in data/samples/stations.json.
    """
    rs = sorted((r for r in readings if r.value is not None), key=lambda r: r.period_end)
    if not rs:
        return []
    if location_id is None:
        location_id = _sample_stations()["location"].get(rs[0].sensor_id)
        if location_id is None:
            raise ValueError(f"unknown sensor {rs[0].sensor_id}: pass location_id")
    values = [r.value for r in rs]
    y = np.log1p(np.clip(np.asarray(values, dtype=float), 0.0, None))
    edges = [0, *change_points(values)]
    segments = list(zip(edges, edges[1:]))
    out = []
    for (a0, a1), (b0, b1) in zip(segments, segments[1:]):
        prev_mean = math.expm1(float(y[a0:a1].mean()))
        new_mean = math.expm1(float(y[b0:b1].mean()))
        if new_mean <= prev_mean:
            continue
        big = (band_for(new_mean) - band_for(prev_mean) >= MIN_BAND_STEP) or new_mean >= MIN_RATIO * prev_mean
        lasts = rs[b1 - 1].period_end - rs[b0].period_start >= MIN_DURATION
        if big and lasts:
            out.append(Moment(location_id, rs[b0].period_end.astimezone(UTC), rs[b1 - 1].period_end.astimezone(UTC),
                              "positive", "pelt", f"PELT {prev_mean:.1f} -> {new_mean:.1f} µg/m³"))
    return sorted(out, key=_sort_key)


def _ts(v) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"label time {v!r} must carry a timezone (use Z for UTC)")
    return t.astimezone(UTC)


def load_hand_labels(path: str | Path) -> list[Moment]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    out = []
    for item in doc.get("moments", []):
        kind = item["kind"]
        if kind not in ("positive", "negative"):
            raise ValueError(f"label kind must be positive or negative, got {kind!r}")
        start, end = _ts(item["start"]), _ts(item["end"])
        if end < start:
            raise ValueError(f"label ends before it starts: {item}")
        out.append(Moment(int(item["location_id"]), start, end, kind, "hand", str(item.get("note", ""))))
    return sorted(out, key=lambda m: (m.location_id, *_sort_key(m)))


def _readings_from_db(conn: Connection) -> dict[int, tuple[list[Reading], tzinfo]]:
    """Per station: the latest known version of every reading of its pm25 sensor, and the station tz."""
    bounds = conn.execute(sa.select(sa.func.min(readings_table.c.period_end), sa.func.max(readings_table.c.period_end),
                                    sa.func.max(readings_table.c.ingested_at))).one()
    rows = conn.execute(sa.select(stations.c.id, stations.c.timezone, sensors.c.id.label("sensor_id"))
                        .join(sensors, sensors.c.station_id == stations.c.id)
                        .where(sensors.c.parameter == "pm25").order_by(stations.c.id)).all()
    out = {}
    for row in rows:
        rs = ([] if bounds[0] is None else
              repo.readings_as_of(conn, row.sensor_id, bounds[0], bounds[1], as_of=bounds[2]))
        out[row.id] = (rs, ZoneInfo(row.timezone))
    return out


def all_moments(conn_or_readings_by_location: Connection | Mapping[int, list[Reading]],
                labels_path: str | Path) -> dict[int, list[Moment]]:
    """PELT moments merged with the hand labels, per location, each list ascending by start.

    Accepts a DB connection (every pm25 station, latest known readings) or {location_id: readings}.
    """
    source = conn_or_readings_by_location
    if isinstance(source, Connection):
        per_location = _readings_from_db(source)
    else:
        tzs = _sample_stations()["tz"]
        per_location = {loc: (rs, ZoneInfo(tzs.get(loc, "UTC"))) for loc, rs in source.items()}
    hand = load_hand_labels(labels_path)
    out = {}
    for loc, (rs, tz) in per_location.items():
        merged = reference_moments(rs, tz, location_id=loc) + [m for m in hand if m.location_id == loc]
        out[loc] = sorted(merged, key=_sort_key)
    return out
