"""D1 TRIGGER (S-C §5): which event kinds fire for one user, hour by hour, over a window of shared scores.

The user's sensitivity `k` scales every bar; it never changes a score. The user's own CUSUM is
re-run over the window's `z` series with the user's bar (S-C §4 implementation note), so the shared
`StationScore.cusum` stays sensitivity-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from aqagent import params
from aqagent.types import EVENT_PRECEDENCE, Band, EventKind, StationScore

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class TriggerResult:
    label: EventKind | None
    fired: frozenset[EventKind]
    calm: bool
    near_misses: tuple[str, ...]
    bars: dict[str, float]
    cusum: float = 0.0  # the user's own CUSUM at this hour, before any reset (for the trace)


def _clean(s: StationScore) -> bool:
    return s.excluded is None and s.z is not None


def triggers(window: list[StationScore], k: float, alert_band: Band) -> list[TriggerResult]:
    """One TriggerResult per hour of `window` (oldest first); the last one is the evaluated hour."""
    bars = {
        EventKind.spike.value: params.SPIKE_Z * k,
        EventKind.climb.value: params.CLIMB_BAR * k,
        EventKind.elevated.value: params.ELEVATED_H * k,
        EventKind.floor.value: float(alert_band),
    }
    spike_bar, climb_bar, elevated_bar = bars["spike"], bars["climb"], bars["elevated"]
    spike_need, spike_of = params.SPIKE_CONFIRM
    floor_need, floor_of = params.FLOOR_CONFIRM
    lookback = timedelta(hours=params.FLOOR_LOOKBACK_HOURS)

    bands: dict[datetime, Band] = {
        s.period_end: s.band for s in window if s.excluded is None and s.band is not None
    }

    def floor_confirmed(t: datetime) -> bool:
        hits = sum(1 for j in range(floor_of) if (b := bands.get(t - j * HOUR)) is not None and b >= alert_band)
        return hits >= floor_need

    def band_at_or_before(t: datetime) -> Band | None:
        known = [pt for pt in bands if pt <= t]
        return bands[max(known)] if known else None

    out: list[TriggerResult] = []
    cusum = 0.0
    recent_z: list[float] = []  # the last `spike_of` clean hours
    climb_run = 0  # consecutive clean hours with ewma above the climb bar

    for s in window:
        if not _clean(s):
            out.append(TriggerResult(None, frozenset(), False, (), bars, cusum))
            continue

        if s.gap_break:  # S-C §2: a gap > 3h restarts short-term memory
            cusum, recent_z, climb_run = 0.0, [], 0
        recent_z = (recent_z + [s.z])[-spike_of:]
        cusum = max(0.0, cusum + s.z - params.CUSUM_KREF)
        ewma = s.ewma
        slope = s.slope_6h
        rising = slope is not None and slope > params.CLIMB_SLOPE
        climb_run = climb_run + 1 if ewma is not None and ewma > climb_bar else 0

        fired: set[EventKind] = set()
        if sum(1 for z in recent_z if z >= spike_bar) >= spike_need:
            fired.add(EventKind.spike)
        if climb_run >= params.CLIMB_HOURS and rising:
            fired.add(EventKind.climb)
        cusum_now = cusum
        if cusum > elevated_bar and ewma is not None and ewma >= params.ELEVATED_MIN_EWMA:
            fired.add(EventKind.elevated)
            cusum = 0.0
        t = s.period_end
        before = band_at_or_before(t - lookback)
        if floor_confirmed(t) and not floor_confirmed(t - HOUR) and before is not None and before < alert_band:
            fired.add(EventKind.floor)

        near: list[str] = []
        if EventKind.spike not in fired and s.z >= params.NEAR_MISS_FRACTION * spike_bar:
            near.append(EventKind.spike.value)
        if EventKind.climb not in fired and rising and ewma is not None and ewma >= params.NEAR_MISS_FRACTION * climb_bar:
            near.append(EventKind.climb.value)
        if EventKind.elevated not in fired and cusum_now >= params.NEAR_MISS_FRACTION * elevated_bar:
            near.append(EventKind.elevated.value)

        calm = (
            not fired
            and ewma is not None
            and ewma < params.CALM_EWMA
            and s.band is not None
            and s.typical_band is not None
            and s.band <= s.typical_band
        )
        label = next((kind for kind in EVENT_PRECEDENCE if kind in fired), None)
        out.append(TriggerResult(label, frozenset(fired), calm, tuple(near), bars, cusum_now))
    return out
