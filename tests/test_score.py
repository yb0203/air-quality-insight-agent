import math
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from aqagent import params
from aqagent.sense.validate import validate
from aqagent.types import Band, ReasonCode, Reading
from aqagent.understand.aqi import band_for, nowcast
from aqagent.understand.baseline import fit_baseline
from aqagent.understand.score import score_hours
from tests.fixtures import UTC, hourly, sample_readings

H1 = timedelta(hours=1)
UTCZ = ZoneInfo("UTC")
START = datetime(2026, 9, 1, 1, tzinfo=UTC)
FLAT = 10.0
Y0 = math.log1p(FLAT)


def v_for_z(z: float) -> float:
    """Value whose z is `z` against a flat-10 history (m = log1p(10), s floored at 0.15)."""
    return math.expm1(Y0 + params.MAD_FLOOR * z)


def history(hours: int = 14 * 24) -> list[Reading]:
    """Flat 10 µg/m³, every 5th hour at 9.5 so the sensor never looks stuck.

    Every hour bucket keeps a majority of exact 10s, so m_h = log1p(10) and s_h is floored at 0.15.
    """
    return hourly(START, [FLAT - 0.5 if i % 5 == 4 else FLAT for i in range(hours)])


def z_of(v: float) -> float:
    return (math.log1p(v) - Y0) / params.MAD_FLOOR


def ewma_of(values) -> float:
    e = None
    for v in values:
        z = z_of(v)
        e = z if e is None else params.EWMA_LAMBDA * z + (1 - params.EWMA_LAMBDA) * e
    return e


def window_values(rs, hour, skip=()):
    lo = hour - timedelta(hours=params.SCORE_WINDOW_HOURS)
    return [r.value for r in rs if lo < r.period_end <= hour and r.period_end not in skip]


def after(rs: list[Reading], values) -> list[Reading]:
    return rs + hourly(rs[-1].period_end + H1, values)


def score_one(rs, hour, as_of=None):
    return score_hours(rs, UTCZ, [hour], as_of or rs[-1].period_end)[0]


def test_score_values():
    rs = after(history(), [v_for_z(3)] * 5)
    hours = [r.period_end for r in rs[-6:]]
    scores = score_hours(rs, UTCZ, hours, rs[-1].period_end)
    assert [s.period_end for s in scores] == hours
    assert [s.z for s in scores] == pytest.approx([0, 3, 3, 3, 3, 3])
    # EWMA lambda 0.3, seeded with z at the start of the 72 h window
    assert [s.ewma for s in scores] == pytest.approx([ewma_of(window_values(rs, h)) for h in hours])
    assert 0.8 < scores[1].ewma < 0.95  # ~0.3 * 3 after a calm (slightly dithered) window
    # CUSUM max(0, c + z - 0.5): 2.5, 5, 7.5, 10 (> 8 with ewma >= 0.5 -> reset after), then 2.5
    assert [s.cusum for s in scores] == pytest.approx([0, 2.5, 5.0, 7.5, 10.0, 2.5])
    last = scores[-1]
    assert last.excluded is None and last.gap_break is False
    assert last.typical_band is band_for(FLAT)
    assert last.evidence["m_h"] == pytest.approx(Y0)
    assert last.evidence["s_h"] == pytest.approx(params.MAD_FLOOR)
    assert last.evidence["value"] == pytest.approx(v_for_z(3))
    assert last.evidence["n_hours"] == 14 * 24
    nc = nowcast([(i, r.value) for i, r in enumerate(reversed(rs[-12:]))])
    assert last.nowcast == nc and last.band is band_for(nc)
    assert last.sensor_id == 1


def test_score_z_uses_the_hour_of_day_baseline():
    # each local hour has its own level; a value at hour 6's usual level is unremarkable at hour 6
    rs = hourly(START, [FLAT * (1 + (i % 24) / 4) for i in range(14 * 24 + 7)])
    s = score_one(rs, rs[-1].period_end)  # period_start hour 6
    b = fit_baseline(validate(rs), UTCZ, rs[-1].period_end)
    m, sd = b.expected(6)
    assert s.z == pytest.approx((math.log1p(rs[-1].value) - m) / sd)
    assert s.evidence["m_h"] == pytest.approx(m) and s.evidence["s_h"] == pytest.approx(sd)


def test_score_slope_theil_sen():
    ys = [Y0 + 0.1 * i for i in range(6)]
    ys[2] += 0.5  # one outlier: 10 of 15 pairwise slopes are still exactly 0.1
    rs = after(history(), [math.expm1(y) for y in ys])
    s = score_one(rs, rs[-1].period_end)
    assert s.slope_6h == pytest.approx(0.1)


def test_score_slope_needs_three_clean_points():
    rs = after(history(), [FLAT])
    rs = rs + hourly(rs[-1].period_end + 5 * H1, [FLAT * 2])  # 4 missing hours before
    s = score_one(rs, rs[-1].period_end)
    assert s.slope_6h is None
    assert s.nowcast is None  # needs 2 of the 3 most recent hours


def test_qa_det_11_deterministic():
    rs = sample_readings(4712609)
    tz = ZoneInfo("Asia/Kolkata")
    hours = [r.period_end for r in rs[-48:]]
    a = score_hours(rs, tz, hours, rs[-1].period_end)
    shuffled = rs[:]
    random.Random(7).shuffle(shuffled)
    b = score_hours(shuffled, tz, hours, rs[-1].period_end)
    assert a == b
    assert sum(s.z is not None for s in a) >= 40


def test_score_gap_resets_ewma():
    rs = after(history(), [v_for_z(3)] * 3)
    rs = rs + hourly(rs[-1].period_end + 5 * H1, [FLAT, v_for_z(3)])  # 4 missing hours, then data
    first, second = rs[-2].period_end, rs[-1].period_end
    before = score_one(rs, rs[-3].period_end)
    assert before.ewma > 1 and before.cusum > 5
    s1, s2 = score_hours(rs, UTCZ, [first, second], rs[-1].period_end)
    assert s1.gap_break is True and s2.gap_break is False
    assert s1.z == pytest.approx(0) and s1.ewma == pytest.approx(0) and s1.cusum == 0
    assert s2.ewma == pytest.approx(0.9) and s2.cusum == pytest.approx(2.5)


def test_score_three_missing_hours_do_not_reset():
    rs = after(history(), [v_for_z(3)] * 3)
    rs = rs + hourly(rs[-1].period_end + 4 * H1, [FLAT])  # 3 missing hours
    s = score_one(rs, rs[-1].period_end)
    assert s.gap_break is False and s.ewma > 0.5


def test_score_excluded_hours():
    rs = after(history(), [75, 980, 90])
    glitch = rs[-2].period_end
    s = score_one(rs, glitch)
    assert s.excluded is ReasonCode.DQ_SUSPECT
    assert (s.z, s.ewma, s.cusum) == (None, None, None)
    assert s.evidence["value"] == 980
    after_glitch = score_one(rs, rs[-1].period_end)
    assert after_glitch.excluded is None
    assert after_glitch.evidence["excluded_in_window"] == {"DQ_SUSPECT": 1}
    # the glitch hour never feeds EWMA, CUSUM, slope or NowCast
    h = rs[-1].period_end
    assert after_glitch.ewma == pytest.approx(ewma_of(window_values(rs, h, skip={glitch})))
    assert z_of(75) - 0.5 > params.ELEVATED_H  # the 75 hour alone crosses the bar, so CUSUM restarts
    assert after_glitch.cusum == pytest.approx(z_of(90) - 0.5)
    missing = rs[-1].period_end + H1
    s = score_hours(rs, UTCZ, [missing], missing)[0]
    assert s.excluded is ReasonCode.NO_DATA and s.z is None
    assert s.period_end == missing and s.sensor_id == 1


def test_qa_dq_07_no_baseline_score():
    rs = history(72)
    s = score_one(rs, rs[-1].period_end)  # only 71 clean hours before it
    assert s.excluded is ReasonCode.NO_BASELINE
    assert (s.z, s.ewma, s.cusum, s.typical_band) == (None, None, None, None)
    assert s.evidence["n_hours"] == 71
    assert score_one(after(rs, [FLAT]), rs[-1].period_end + H1).excluded is None


def test_qa_dq_05_provisional_hour_is_rescored():
    rs = after(history(), [30, 200])
    newest = rs[-1].period_end
    s = score_one(rs, newest)
    assert s.excluded is None and s.z > 3 and s.evidence["provisional"] is True
    rs = after(rs, [30])
    again = score_hours(rs, UTCZ, [newest], rs[-1].period_end)[0]
    assert again.excluded is ReasonCode.DQ_SUSPECT and again.z is None
    # readings newer than as_of are not known yet
    assert score_hours(rs, UTCZ, [newest], newest)[0] == s


def test_score_cusum_resets_after_default_elevated_bar():
    rs = after(history(), [v_for_z(5), v_for_z(5), FLAT])  # one isolated big hour would be DQ_SUSPECT
    s0, s1, s2 = score_hours(rs, UTCZ, [r.period_end for r in rs[-3:]], rs[-1].period_end)
    assert s0.cusum == pytest.approx(4.5)
    assert s1.cusum == pytest.approx(9.0) and s1.ewma > params.ELEVATED_MIN_EWMA
    assert s2.cusum == 0  # reset after exceeding 8, then max(0, 0 + 0 - 0.5); no reset would give 8.5


def test_score_cusum_reset_needs_elevated_ewma():
    # a long run far below normal drags EWMA negative while CUSUM sits at 0
    lows = [v_for_z(-5 - 0.1 * i) for i in range(10)]
    rs = after(history(), lows + [v_for_z(5), v_for_z(5), FLAT])
    s1, s2 = score_hours(rs, UTCZ, [rs[-2].period_end, rs[-1].period_end], rs[-1].period_end)
    assert s1.cusum == pytest.approx(9.0) and s1.ewma < params.ELEVATED_MIN_EWMA
    assert s2.cusum == pytest.approx(8.5)  # "elevated" would not fire, so no reset


def test_score_rejects_mixed_sensors_and_needs_sensor_for_empty():
    rs = history(24) + [Reading(2, START, START - H1, 1.0, 100.0)]
    with pytest.raises(ValueError):
        score_hours(rs, UTCZ, [START], START)
    with pytest.raises(ValueError):
        score_hours([], UTCZ, [START], START)
    s = score_hours([], UTCZ, [START], START, sensor_id=9)[0]
    assert s.sensor_id == 9 and s.excluded is ReasonCode.NO_DATA and s.band is None


def test_score_band_for_typical_sample_station():
    rs = sample_readings(4588)
    s = score_hours(rs, ZoneInfo("Europe/Helsinki"), [rs[-1].period_end], rs[-1].period_end)[0]
    assert s.typical_band is Band.GOOD
