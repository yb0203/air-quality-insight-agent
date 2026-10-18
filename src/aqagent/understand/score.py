"""U2 SCORE: shared per-station scores (S-C §4). Pure; recomputed from the readings known as of `as_of`.

Each requested hour H gets: validate -> baseline over the 14 days before H -> z for every clean hour in
the 72 h window ending at H (all against that one baseline) -> EWMA and the default-bar CUSUM over that
window, restarting at the window start and after every gap of more than GAP_RESET_HOURS between clean
hours -> Theil-Sen slope of log1p over the last 6 h -> NowCast over the last 12 clean hours -> bands.
"""
from __future__ import annotations

import bisect
import math
import statistics
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aqagent import params
from aqagent.sense.validate import gap_breaks, validate
from aqagent.types import CheckedReading, Reading, ReasonCode, StationScore
from aqagent.understand import aqi
from aqagent.understand.baseline import Baseline, fit_baseline, local_hour

HOUR = timedelta(hours=1)
_ELEVATED_BAR = params.ELEVATED_H * params.SENSITIVITY_K["default"]


def theil_sen(points: list[tuple[float, float]]) -> float | None:
    """Median of pairwise slopes; None with fewer than 3 points."""
    if len(points) < 3:
        return None
    slopes = [
        (y2 - y1) / (x2 - x1)
        for i, (x1, y1) in enumerate(points)
        for x2, y2 in points[i + 1 :]
        if x2 != x1
    ]
    return statistics.median(slopes)


def _hours_ago(hour: datetime, end: datetime) -> float:
    return (hour - end) / HOUR


class _Series:
    """Readings known as of one evaluation, indexed for the per-hour windows."""

    def __init__(self, checked: list[CheckedReading]):
        self.checked = checked
        self.ends = [c.reading.period_end for c in checked]
        self.by_end = {c.reading.period_end: c for c in checked}
        self.clean = [c for c in checked if c.excluded is None]
        self.clean_ends = [c.reading.period_end for c in self.clean]
        self.breaks = gap_breaks([c.reading for c in self.clean])

    def checked_between(self, lo: datetime, hi: datetime) -> list[CheckedReading]:
        """period_end in (lo, hi]."""
        return self.checked[bisect.bisect_right(self.ends, lo) : bisect.bisect_right(self.ends, hi)]

    def clean_between(self, lo: datetime, hi: datetime) -> list[CheckedReading]:
        """period_end in (lo, hi]."""
        return self.clean[bisect.bisect_right(self.clean_ends, lo) : bisect.bisect_right(self.clean_ends, hi)]


def _baseline_at(series: _Series, tz: ZoneInfo, hour: datetime) -> tuple[Baseline | None, int]:
    lo = hour - timedelta(days=params.BASELINE_DAYS)
    i, j = bisect.bisect_left(series.ends, lo), bisect.bisect_left(series.ends, hour)
    pool = series.checked[i:j]
    return fit_baseline(pool, tz, hour), sum(1 for c in pool if c.excluded is None)


def _z(c: CheckedReading, b: Baseline, tz: ZoneInfo) -> float:
    m, s = b.expected(local_hour(c.reading, tz))
    return (math.log1p(c.reading.value) - m) / s


def _ewma_cusum(window: list[CheckedReading], breaks: set[datetime], b: Baseline, tz: ZoneInfo):
    """(z, ewma, cusum) at the window's last hour. Restarts at the first hour and after each gap break."""
    z = ewma = None
    cusum = 0.0
    fired = False  # the default-bar "elevated" signal fired on the previous hour
    for c in window:
        z = _z(c, b, tz)
        if ewma is None or c.reading.period_end in breaks:
            ewma, cusum = z, 0.0
        else:
            ewma = params.EWMA_LAMBDA * z + (1 - params.EWMA_LAMBDA) * ewma
            if fired:
                cusum = 0.0
        cusum = max(0.0, cusum + min(z, params.CUSUM_CLIP) - params.CUSUM_KREF)
        fired = cusum > _ELEVATED_BAR and ewma >= params.ELEVATED_MIN_EWMA
    return z, ewma, cusum


def _score_one(series: _Series, tz: ZoneInfo, hour: datetime, sensor_id: int) -> StationScore:
    here = series.by_end.get(hour)
    baseline, n_hours = _baseline_at(series, tz, hour)
    window = series.clean_between(hour - timedelta(hours=params.SCORE_WINDOW_HOURS), hour)
    in_window = series.checked_between(hour - timedelta(hours=params.SCORE_WINDOW_HOURS), hour)
    excluded_counts = Counter(c.excluded.value for c in in_window if c.excluded is not None)

    recent = series.clean_between(hour - timedelta(hours=params.NOWCAST_HOURS), hour)
    nowcast = aqi.nowcast([(int(_hours_ago(hour, c.reading.period_end)), c.reading.value) for c in recent])
    last6 = series.clean_between(hour - timedelta(hours=params.SLOPE_HOURS), hour)
    slope = theil_sen([(-_hours_ago(hour, c.reading.period_end), math.log1p(c.reading.value)) for c in last6])

    evidence: dict = {
        "value": here.reading.value if here else None,
        "m_h": None,
        "s_h": None,
        "n_hours": n_hours,
        "hour_local": local_hour(here.reading, tz) if here else None,
        "provisional": here.provisional if here else False,
        "excluded_in_window": dict(sorted(excluded_counts.items())),
    }
    if baseline is not None and here is not None:
        evidence["m_h"], evidence["s_h"] = baseline.expected(local_hour(here.reading, tz))

    if here is None:
        excluded = ReasonCode.NO_DATA
    elif here.excluded is not None:
        excluded = here.excluded
    elif baseline is None:
        excluded = ReasonCode.NO_BASELINE
    else:
        excluded = None

    z = ewma = cusum = None
    if excluded is None:
        z, ewma, cusum = _ewma_cusum(window, series.breaks, baseline, tz)

    return StationScore(
        sensor_id=sensor_id,
        period_end=hour,
        z=z,
        ewma=ewma,
        cusum=cusum,
        slope_6h=slope,
        nowcast=nowcast,
        band=aqi.band_for(nowcast) if nowcast is not None else None,
        typical_band=baseline.typical_band if baseline else None,
        excluded=excluded,
        gap_break=excluded is None and hour in series.breaks,
        evidence=evidence,
    )


def score_hours(
    readings_known: list[Reading],
    tz: ZoneInfo,
    hours: list[datetime],
    as_of: datetime,
    *,
    sensor_id: int | None = None,
) -> list[StationScore]:
    """One StationScore per requested hour, in the order given, from the readings known as of `as_of`.

    Readings with period_end after `as_of` are ignored. `sensor_id` is inferred from the readings and
    is only needed when there are none (the sensor has gone silent).
    """
    known = [r for r in readings_known if r.period_end <= as_of]
    ids = {r.sensor_id for r in known}
    if sensor_id is not None:
        ids.add(sensor_id)
    if len(ids) != 1:
        raise ValueError(f"score_hours needs exactly one sensor, got {sorted(ids) or 'none'}")
    sid = ids.pop()
    series = _Series(validate(known, provisional_last=True))
    return [_score_one(series, tz, h, sid) for h in hours]
