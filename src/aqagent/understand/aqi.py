"""U2 'how harmful': EPA NowCast and the 2024 PM2.5 AQI bands (S-B §2, S-C §4)."""
from __future__ import annotations

import math

from aqagent import params
from aqagent.types import Band

# (upper concentration µg/m³, band, AQI low, AQI high, concentration low), 2024 revision
_BREAKPOINTS = [
    (9.0, Band.GOOD, 0, 50, 0.0),
    (35.4, Band.MODERATE, 51, 100, 9.1),
    (55.4, Band.USG, 101, 150, 35.5),
    (125.4, Band.UNHEALTHY, 151, 200, 55.5),
    (225.4, Band.VERY_UNHEALTHY, 201, 300, 125.5),
    (325.4, Band.HAZARDOUS, 301, 500, 225.5),
]


def _truncate(c: float) -> float:
    return math.floor(c * 10) / 10


def band_for(pm25: float) -> Band:
    c = _truncate(pm25)
    for hi, band, *_ in _BREAKPOINTS:
        if c <= hi:
            return band
    return Band.HAZARDOUS


def aqi_value(pm25: float) -> int:
    c = _truncate(max(pm25, 0.0))
    for hi, _band, i_lo, i_hi, c_lo in _BREAKPOINTS:
        if c <= hi:
            return round((i_hi - i_lo) / (hi - c_lo) * (c - c_lo) + i_lo)
    return 500


def nowcast(window: list[tuple[int, float]]) -> float | None:
    """`window` holds (hours_ago, clean value) pairs. Valid only with 2 of the 3 most recent hours."""
    pts = [(h, c) for h, c in window if 0 <= h < params.NOWCAST_HOURS and c is not None]
    if sum(1 for h, _ in pts if h < 3) < 2:
        return None
    values = [c for _, c in pts]
    hi, lo = max(values), min(values)
    w = 1.0 if hi <= 0 else max(0.5, 1 - (hi - lo) / hi)
    num = sum(w**h * c for h, c in pts)
    den = sum(w**h for h, _ in pts)
    return _truncate(num / den)
