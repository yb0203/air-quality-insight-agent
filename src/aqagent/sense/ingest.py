"""S1: one ingestion run (S-A §4). Trailing 24 h window per sensor, backfill when stale, revisions kept.

One failing sensor never stops the run: its `ingestion_runs` row is `error`, and the next run's window
(or backfill) picks its hours up again.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.engine import Connection

from aqagent import params, repo
from aqagent.clock import Clock
from aqagent.types import Reading

log = logging.getLogger(__name__)


class HoursSource(Protocol):
    last_ratelimit_remaining: int | None

    def hours(self, sensor_id: int, dt_from: datetime, dt_to: datetime) -> list[Reading]: ...


@dataclass
class IngestReport:
    changed: dict[int, list[datetime]] = field(default_factory=dict)  # sensor -> new or revised period_ends
    new: int = 0
    revised: int = 0
    runs: dict[int, int] = field(default_factory=dict)    # sensor -> ingestion_runs.id
    errors: dict[int, str] = field(default_factory=dict)  # sensor -> error text

    @property
    def status(self) -> str:
        """'ok' | 'partial' (some sensors failed) | 'error' (all failed)."""
        if not self.errors:
            return "ok"
        return "error" if len(self.errors) == len(self.runs) else "partial"


def _window(conn: Connection, sensor_id: int, now: datetime) -> tuple[str, datetime]:
    trailing = timedelta(hours=params.TRAILING_WINDOW_HOURS)
    newest = repo.newest_reading_at(conn, sensor_id, as_of=now)
    if newest is not None and newest >= now - trailing:
        return "hourly", now - trailing
    earliest = now - timedelta(days=params.BACKFILL_DAYS)
    if newest is None:
        return "backfill", earliest
    return "backfill", max(earliest, newest - trailing)  # keep the usual overlap so revisions are caught


def run_ingestion(conn: Connection, client: HoursSource, clock: Clock, sensor_ids: list[int]) -> IngestReport:
    report = IngestReport()
    for sensor_id in sensor_ids:
        started = clock.now()
        kind, dt_from = _window(conn, sensor_id, started)
        run_id = repo.start_run(conn, kind=kind, sensor_id=sensor_id, started_at=started,
                                window_from=dt_from, window_to=started)
        report.runs[sensor_id] = run_id
        try:
            rows = client.hours(sensor_id, dt_from, started)
        except Exception as e:  # one sensor's failure (404, 500, network, parse) must not stop the run
            msg = f"{type(e).__name__}: {e}"
            log.warning("ingestion of sensor %s failed: %s", sensor_id, msg)
            report.errors[sensor_id] = msg
            repo.finish_run(conn, run_id, finished_at=clock.now(), status="error", rows_fetched=0, rows_new=0,
                            rows_revised=0, error=msg, ratelimit_remaining=client.last_ratelimit_remaining,
                            newest_period_end=repo.newest_reading_at(conn, sensor_id, as_of=started))
            continue
        ingested_at = clock.now()
        new, revised = repo.upsert_readings_detailed(conn, rows, ingested_at=ingested_at, run_id=run_id)
        if new or revised:
            report.changed[sensor_id] = sorted(new + revised)
        report.new += len(new)
        report.revised += len(revised)
        repo.finish_run(conn, run_id, finished_at=clock.now(), status="ok", rows_fetched=len(rows),
                        rows_new=len(new), rows_revised=len(revised),
                        newest_period_end=repo.newest_reading_at(conn, sensor_id, as_of=ingested_at),
                        ratelimit_remaining=client.last_ratelimit_remaining)
        log.info("sensor %s: %s run, %d fetched, %d new, %d revised", sensor_id, kind, len(rows), len(new),
                 len(revised))
    return report
