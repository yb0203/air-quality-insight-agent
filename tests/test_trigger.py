"""D1 TRIGGER (S-C §5). Windows are built directly from StationScore values, not from readings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aqagent.decide.trigger import TriggerResult, triggers
from aqagent.types import Band, EventKind, ReasonCode, StationScore

UTC = timezone.utc
T0 = datetime(2026, 10, 1, tzinfo=UTC)
VU = Band.VERY_UNHEALTHY


def _per_hour(value, n):
    return list(value) if isinstance(value, (list, tuple)) else [value] * n


def win(n, z=0.0, ewma=0.0, slope=0.0, band=Band.GOOD, typical=Band.MODERATE, excluded=None):
    """n hourly StationScores; each field is a scalar (every hour) or a list (one value per hour)."""
    cols = [_per_hour(c, n) for c in (z, ewma, slope, band, typical, excluded)]
    assert all(len(c) == n for c in cols)
    return [
        StationScore(
            sensor_id=1,
            period_end=T0 + timedelta(hours=i),
            z=zi,
            ewma=ei,
            cusum=None,
            slope_6h=si,
            nowcast=None,
            band=bi,
            typical_band=ti,
            excluded=xi,
        )
        for i, (zi, ei, si, bi, ti, xi) in enumerate(zip(*cols))
    ]


def fired_at(results: list[TriggerResult], kind: EventKind) -> list[int]:
    return [i for i, r in enumerate(results) if kind in r.fired]


def test_one_result_per_hour_last_is_evaluated_hour():
    results = triggers(win(5), 1.0, VU)
    assert len(results) == 5
    assert results[-1].bars == {"spike": 3.5, "climb": 1.26, "elevated": 8.0, "floor": float(VU)}


def test_qa_det_03_spike_two_of_three():
    assert fired_at(triggers(win(3, z=[0, 4, 0]), 1.0, VU), EventKind.spike) == []
    results = triggers(win(3, z=[4, 0, 4]), 1.0, VU)
    assert EventKind.spike in results[-1].fired
    assert results[-1].label is EventKind.spike


def test_qa_det_04_climb_three_hours_and_rising():
    two = triggers(win(5, ewma=[0, 0, 0, 1.3, 1.3], slope=0.02), 1.0, VU)
    assert fired_at(two, EventKind.climb) == []
    three = triggers(win(5, ewma=[0, 0, 1.3, 1.3, 1.3], slope=0.02), 1.0, VU)
    assert fired_at(three, EventKind.climb) == [4]
    assert three[-1].label is EventKind.climb


def test_qa_det_15_flat_plateau_is_elevated_not_climb():
    # z 2.5 adds 2.0 per hour to the CUSUM: 2, 4, 6, 8 (not > 8), 10 -> fires at hour 4, then resets.
    results = triggers(win(6, z=2.5, ewma=1.5, slope=0.0), 1.0, VU)
    assert fired_at(results, EventKind.climb) == []
    assert fired_at(results, EventKind.elevated) == [4]
    assert results[4].label is EventKind.elevated


def test_qa_det_05_elevated_slow_build():
    # z 1.5 adds 1.0 per hour: the CUSUM first exceeds 8 at hour 8 (value 9), then restarts from 0.
    results = triggers(win(12, z=1.5, ewma=1.0, slope=0.02), 1.0, VU)
    assert fired_at(results, EventKind.spike) == []
    assert fired_at(results, EventKind.climb) == []
    assert fired_at(results, EventKind.elevated) == [8]
    assert results[8].cusum == 9.0
    assert results[9].cusum == 1.0


def test_qa_det_06_elevated_needs_ewma():
    results = triggers(win(12, z=3.0, ewma=0.4), 1.0, VU)
    assert results[-1].cusum > 8
    assert fired_at(results, EventKind.elevated) == []
    assert all(r.label is None for r in results)


def test_qa_det_08_floor_edge_triggered():
    alert = Band.UNHEALTHY
    bands = [Band.MODERATE] * 8 + [Band.UNHEALTHY] * 48
    results = triggers(win(len(bands), band=bands), 1.0, alert)
    assert fired_at(results, EventKind.floor) == [9]
    assert results[9].label is EventKind.floor


def test_floor_needs_two_of_three():
    bands = [Band.MODERATE] * 8 + [Band.UNHEALTHY] + [Band.MODERATE] * 3
    assert fired_at(triggers(win(len(bands), band=bands), 1.0, Band.UNHEALTHY), EventKind.floor) == []


def test_floor_does_not_refire_after_a_short_dip():
    bands = [Band.MODERATE] * 8 + [Band.UNHEALTHY] * 4 + [Band.MODERATE] * 2 + [Band.UNHEALTHY] * 4
    assert fired_at(triggers(win(len(bands), band=bands), 1.0, Band.UNHEALTHY), EventKind.floor) == [9]


def test_qa_det_09_near_miss():
    results = triggers(win(3, z=[0, 3.0, 3.0]), 1.0, VU)
    assert "spike" in results[-1].near_misses
    assert results[-1].fired == frozenset()
    assert results[-1].label is None


def test_near_miss_climb_and_elevated():
    # EWMA 1.1 >= 0.8 x 1.26 and rising; CUSUM after 4 h of z 2.2 is 6.8 >= 0.8 x 8.
    results = triggers(win(4, z=2.2, ewma=1.1, slope=0.02), 1.0, VU)
    assert results[-1].fired == frozenset()
    assert {"climb", "elevated"} <= set(results[-1].near_misses)
    flat = triggers(win(4, ewma=1.1, slope=0.0), 1.0, VU)
    assert "climb" not in flat[-1].near_misses


def test_qa_det_14_one_label_by_precedence():
    # Hour 2: spike (2 of 3 at z 4), climb (3 h above 1.26, rising) and elevated (CUSUM 10.5 > 8) all fire.
    results = triggers(win(4, z=4.0, ewma=1.5, slope=0.02), 1.0, VU)
    assert {EventKind.spike, EventKind.climb, EventKind.elevated} <= results[2].fired
    assert results[2].label is EventKind.spike


def test_qa_sens_01_high_sensitivity():
    window = win(3, z=[0, 3.0, 3.0])
    assert EventKind.spike in triggers(window, 0.75, VU)[-1].fired
    assert EventKind.spike not in triggers(window, 1.0, VU)[-1].fired


def test_qa_sens_02_low_sensitivity():
    window = win(3, z=[0, 4.0, 4.0])
    assert EventKind.spike in triggers(window, 1.0, VU)[-1].fired
    assert EventKind.spike not in triggers(window, 1.25, VU)[-1].fired


def test_calm_hour():
    assert triggers(win(1, ewma=0.4, band=Band.MODERATE, typical=Band.MODERATE), 1.0, VU)[-1].calm is True
    assert triggers(win(1, ewma=0.4, band=Band.USG, typical=Band.MODERATE), 1.0, VU)[-1].calm is False
    assert triggers(win(1, ewma=0.6, band=Band.GOOD, typical=Band.MODERATE), 1.0, VU)[-1].calm is False


def test_calm_needs_nothing_fired():
    results = triggers(win(3, z=[4, 4, 4], ewma=0.0), 1.0, VU)
    assert EventKind.spike in results[-1].fired
    assert results[-1].calm is False


def test_excluded_hour_never_fires_and_is_not_clean():
    suspect = ReasonCode.DQ_SUSPECT
    results = triggers(win(3, z=[4, 4, 0], excluded=[None, suspect, None]), 1.0, VU)
    assert fired_at(results, EventKind.spike) == []
    assert results[1].calm is False and results[1].near_misses == ()
    # The excluded hour is skipped: the last 3 clean hours are hours 0 and 2.
    skipped = triggers(win(3, z=[4, 9, 4], excluded=[None, suspect, None]), 1.0, VU)
    assert fired_at(skipped, EventKind.spike) == [2]


def test_qa_dq_08_gap_resets_user_cusum():
    from dataclasses import replace

    w = win(8, z=1.2, ewma=1.0)  # +0.7 per hour, stays below the elevated bar (8) for 8 hours
    w[6] = replace(w[6], gap_break=True)  # a >3h gap ended just before hour 6
    r = triggers(w, k=1.0, alert_band=Band.VERY_UNHEALTHY)
    assert r[5].cusum == pytest.approx(6 * 0.7)
    assert r[6].cusum == pytest.approx(0.7)  # restarted at the gap


def test_qa_dq_08_gap_resets_spike_memory():
    from dataclasses import replace

    w = win(6, z=[0, 0, 0, 0, 4.0, 4.0], ewma=0.0)
    assert EventKind.spike in triggers(w, 1.0, Band.VERY_UNHEALTHY)[5].fired  # 2 of 3 without a gap
    w[5] = replace(w[5], gap_break=True)
    assert EventKind.spike not in triggers(w, 1.0, Band.VERY_UNHEALTHY)[5].fired  # memory restarts at the gap
