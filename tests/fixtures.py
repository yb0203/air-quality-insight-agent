"""Synthetic data builders shared by the tests."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from aqagent.types import Reading

UTC = timezone.utc
SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "samples" / "openaq_pm25_hourly_90d.csv"


def hourly(start: datetime, values, sensor_id: int = 1, coverage: float = 100.0) -> list[Reading]:
    """One Reading per hour starting at `start` (the first period_end). None values are skipped (a gap)."""
    out = []
    for i, v in enumerate(values):
        end = start + timedelta(hours=i)
        if v is None:
            continue
        out.append(Reading(sensor_id, end, end - timedelta(hours=1), float(v), coverage))
    return out


@lru_cache(maxsize=None)
def _sample_rows() -> tuple:
    with SAMPLE_CSV.open() as f:
        return tuple(csv.DictReader(f))


def sample_readings(location_id: int) -> list[Reading]:
    out = []
    for r in _sample_rows():
        if int(r["location_id"]) != location_id:
            continue
        end = datetime.fromisoformat(r["period_end_utc"].replace("Z", "+00:00"))
        start = datetime.fromisoformat(r["period_start_utc"].replace("Z", "+00:00"))
        cov = float(r["percent_coverage"]) if r["percent_coverage"] else None
        out.append(Reading(int(r["sensor_id"]), end, start, float(r["value_ugm3"]), cov))
    return sorted(out, key=lambda x: x.period_end)
