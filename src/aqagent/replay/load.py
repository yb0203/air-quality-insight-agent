"""Load the recorded sample into `readings` as it would have been known live (S-A §5 "Replay", FR-EVAL-5).

Every row gets `ingested_at = period_end + lag_hours`, the typical OpenAQ publication lag, so an as-of
read at time T sees only the hours a live run at T could have seen.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import Connection

from aqagent import repo
from aqagent.db import UTC
from aqagent.types import Reading

TRACKED = {4588, 7936, 6206921, 6096447, 4712609}  # Helsinki, Los Angeles, Bengaluru, Dubai, Delhi
FIXTURES = {8039, 8118}  # Mumbai glitches, Delhi AirNow gaps

PM25_UNITS = "µg/m³"


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def load_stations(conn: Connection, stations_path: str | Path, location_ids: set[int] | None = None) -> dict[int, int]:
    """Upsert the stations and their pm25 sensors from stations.json; returns {sensor_id: location_id}."""
    sensor_to_location: dict[int, int] = {}
    for s in json.loads(Path(stations_path).read_text()):
        loc = int(s["location_id"])
        if location_ids is not None and loc not in location_ids:
            continue
        lic = (s.get("licenses") or [{}])[0]
        repo.upsert_station(
            conn, id=loc, city=s["city"], name=s["name"], provider=s["provider"], timezone=s["timezone"],
            is_reference=bool(s["is_monitor"]), instrument=", ".join(s.get("instruments") or []) or None,
            lat=s.get("lat"), lon=s.get("lon"), license=lic.get("license"), attribution=lic.get("attribution"))
        repo.upsert_sensor(conn, id=int(s["pm25_sensor_id"]), station_id=loc, parameter="pm25", units=PM25_UNITS)
        sensor_to_location[int(s["pm25_sensor_id"])] = loc
    return sensor_to_location


def load_sample(conn: Connection, csv_path: str | Path, stations_path: str | Path, lag_hours: float = 1.5,
                location_ids: set[int] | None = None) -> int:
    """Load stations, sensors and readings (as-known); returns the number of readings read from the CSV."""
    sensor_to_location = load_stations(conn, stations_path, location_ids)
    lag = timedelta(hours=lag_hours)
    by_ingested: dict[datetime, list[Reading]] = {}
    with Path(csv_path).open(newline="") as f:
        for r in csv.DictReader(f):
            loc = int(r["location_id"])
            if location_ids is not None and loc not in location_ids:
                continue
            sensor_id = int(r["sensor_id"])
            if sensor_to_location.get(sensor_id) != loc:
                raise ValueError(f"sensor {sensor_id} of location {loc} is not in {stations_path}")
            end = _ts(r["period_end_utc"])
            reading = Reading(sensor_id, end, _ts(r["period_start_utc"]),
                              float(r["value_ugm3"]) if r["value_ugm3"] else None,
                              float(r["percent_coverage"]) if r["percent_coverage"] else None)
            by_ingested.setdefault(end + lag, []).append(reading)
    if not by_ingested:
        return 0
    times = sorted(by_ingested)
    rows = [r for t in times for r in by_ingested[t]]
    run_id = repo.start_run(conn, kind="replay-load", started_at=times[0],
                            window_from=min(r.period_end for r in rows), window_to=max(r.period_end for r in rows))
    new = revised = 0
    for t in times:
        n, v = repo.upsert_readings(conn, by_ingested[t], ingested_at=t, run_id=run_id)
        new, revised = new + n, revised + v
    repo.finish_run(conn, run_id, finished_at=times[-1], status="ok", rows_fetched=len(rows), rows_new=new,
                    rows_revised=revised, newest_period_end=max(r.period_end for r in rows))
    return len(rows)
