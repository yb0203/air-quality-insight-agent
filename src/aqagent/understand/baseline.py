"""U1 LEARN: robust hour-of-day baseline on log1p(PM2.5) (S-C §3). Pure, recomputed per evaluation."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aqagent import params
from aqagent.types import Band, CheckedReading, Reading
from aqagent.understand.aqi import band_for


def local_hour(reading: Reading, tz: ZoneInfo) -> int:
    """Wall-clock hour of day the reading measured (its period_start in the station's timezone).

    Bucketing by the UTC instant converted to local time means a repeated DST hour simply
    contributes two samples to the same bucket, and a skipped one contributes none.
    """
    return reading.period_start.astimezone(tz).hour


def _median_and_s(ys: list[float]) -> tuple[float, float]:
    m = statistics.median(ys)
    return m, params.MAD_SCALE * statistics.median(abs(y - m) for y in ys)


@dataclass(frozen=True)
class Baseline:
    m: dict[int, float]  # raw per-hour median of log1p
    s: dict[int, float]  # raw per-hour 1.4826·MAD of log1p
    m_all: float
    s_all: float
    typical_band: Band
    n_hours: int
    trained_through: datetime
    counts: dict[int, int] = field(default_factory=dict)  # clean samples per local hour

    def expected(self, hour_local: int) -> tuple[float, float]:
        """(m_h, s_h) with shrinkage toward all-hours (weight n/7, all-hours below 2) and the MAD floor."""
        n = self.counts.get(hour_local, 0)
        if n < 2 or hour_local not in self.m:
            m, s = self.m_all, self.s_all
        elif n < params.SHRINK_SAMPLES:
            w = n / params.SHRINK_SAMPLES
            m = w * self.m[hour_local] + (1 - w) * self.m_all
            s = w * self.s[hour_local] + (1 - w) * self.s_all
        else:
            m, s = self.m[hour_local], self.s[hour_local]
        return m, max(params.MAD_FLOOR, s)


def fit_baseline(clean: list[CheckedReading], tz: ZoneInfo, as_of: datetime) -> Baseline | None:
    """Fit on clean readings with period_end in [as_of - BASELINE_DAYS, as_of). None below MIN_HISTORY_HOURS."""
    lo = as_of - timedelta(days=params.BASELINE_DAYS)
    used = [
        c.reading
        for c in clean
        if c.excluded is None and c.reading.value is not None and lo <= c.reading.period_end < as_of
    ]
    if len(used) < params.MIN_HISTORY_HOURS:
        return None
    buckets: dict[int, list[float]] = {}
    for r in used:
        buckets.setdefault(local_hour(r, tz), []).append(math.log1p(r.value))
    m: dict[int, float] = {}
    s: dict[int, float] = {}
    for h, ys in buckets.items():
        m[h], s[h] = _median_and_s(ys)
    m_all, s_all = _median_and_s([y for ys in buckets.values() for y in ys])
    return Baseline(
        m=m,
        s=s,
        m_all=m_all,
        s_all=s_all,
        typical_band=band_for(statistics.median(r.value for r in used)),
        n_hours=len(used),
        trained_through=max(r.period_end for r in used),
        counts={h: len(ys) for h, ys in buckets.items()},
    )
