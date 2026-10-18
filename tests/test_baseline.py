import math
import statistics
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from aqagent import params
from aqagent.sense.validate import validate
from aqagent.types import Band, CheckedReading, Reading, ReasonCode
from aqagent.understand.aqi import band_for
from aqagent.understand.baseline import fit_baseline, local_hour
from tests.fixtures import UTC, hourly, sample_readings

UTCZ = ZoneInfo("UTC")
HELSINKI = ZoneInfo("Europe/Helsinki")
START = datetime(2026, 9, 1, 1, tzinfo=UTC)  # first period_end; period_start 00:00 -> local hour 0
AS_OF = START + timedelta(days=14)  # the window [AS_OF - 14 d, AS_OF) holds exactly 14 days of hours


def clean(readings):
    return [CheckedReading(r) for r in readings]


def mad_s(ys):
    m = statistics.median(ys)
    return params.MAD_SCALE * statistics.median(abs(y - m) for y in ys)


def diurnal_series(sparse_hour=5, sparse_n=3, lonely_hour=7):
    out = []
    for d in range(14):
        for h in range(24):
            if h == sparse_hour and d >= sparse_n:
                continue
            if h == lonely_hour and d >= 1:
                continue
            end = START + timedelta(days=d, hours=h)
            out.append(Reading(1, end, end - timedelta(hours=1), (h + 1) * (1 + 0.1 * d), 100.0))
    return out


def test_qa_det_01_hour_of_day_shrink_floor():
    rs = diurnal_series()
    b = fit_baseline(clean(rs), UTCZ, AS_OF)
    assert b is not None
    ys = {h: [math.log1p(r.value) for r in rs if r.period_start.hour == h] for h in range(24)}
    all_y = [y for v in ys.values() for y in v]
    for h in (0, 12, 23):
        assert b.m[h] == pytest.approx(statistics.median(ys[h]))
        assert b.s[h] == pytest.approx(mad_s(ys[h]))
        assert b.expected(h) == pytest.approx((b.m[h], max(params.MAD_FLOOR, b.s[h])))
    assert b.m_all == pytest.approx(statistics.median(all_y))
    assert b.s_all == pytest.approx(mad_s(all_y))
    # sparse hour: 3 samples -> 3/7 blend toward all-hours
    w = 3 / params.SHRINK_SAMPLES
    m5 = w * statistics.median(ys[5]) + (1 - w) * b.m_all
    s5 = max(params.MAD_FLOOR, w * mad_s(ys[5]) + (1 - w) * b.s_all)
    assert b.expected(5) == pytest.approx((m5, s5))
    # fewer than 2 samples -> all-hours
    assert b.expected(7) == pytest.approx((b.m_all, max(params.MAD_FLOOR, b.s_all)))
    assert b.expected(99) == b.expected(7)  # an hour never seen -> all-hours too
    assert b.n_hours == len(rs)
    assert b.trained_through == rs[-1].period_end
    assert b.typical_band is band_for(statistics.median(r.value for r in rs))


def test_qa_det_01_flat_series_hits_floor():
    rs = hourly(START, [10.0] * (14 * 24))
    b = fit_baseline(clean(rs), UTCZ, AS_OF)
    for h in range(24):
        assert b.expected(h)[1] == params.MAD_FLOOR
        assert b.expected(h)[0] == pytest.approx(math.log1p(10.0))


def test_qa_dq_07_no_baseline():
    end = AS_OF
    rs71 = hourly(end - timedelta(hours=71), [10.0] * 71)
    assert fit_baseline(clean(rs71), UTCZ, end + timedelta(hours=1)) is None
    rs72 = hourly(end - timedelta(hours=72), [10.0] * 72)
    assert fit_baseline(clean(rs72), UTCZ, end + timedelta(hours=1)) is not None


def test_qa_dq_07_only_clean_hours_in_window_count():
    rs = hourly(START, [10.0] * 80)
    checked = [CheckedReading(r, ReasonCode.DQ_SUSPECT if i < 9 else None) for i, r in enumerate(rs)]
    as_of = rs[-1].period_end + timedelta(hours=1)
    assert fit_baseline(checked, UTCZ, as_of) is None  # 71 clean
    assert fit_baseline(clean(rs), UTCZ, as_of) is not None
    # readings at or after as_of, or older than 14 days, are not used
    b = fit_baseline(clean(rs), UTCZ, rs[-1].period_end)
    assert b.n_hours == 79 and b.trained_through == rs[-2].period_end
    far = rs[-1].period_end + timedelta(days=14, hours=10)
    assert fit_baseline(clean(rs), UTCZ, far) is None


def test_review_dst_hour_buckets():
    # Helsinki falls back 2026-10-25 04:00 EEST -> 03:00 EET, so the local 03:00 hour happens twice.
    first = datetime(2026, 10, 25, 0, tzinfo=UTC)  # period_start 03:00 EEST
    second = datetime(2026, 10, 25, 1, tzinfo=UTC)  # period_start 03:00 EET
    # local 2026-10-21 00:00 EEST (20 Oct 21:00 UTC) up to local 2026-10-28 00:00 EET: 7 local days + 1 h
    rs = hourly(datetime(2026, 10, 20, 22, tzinfo=UTC), [5.0] * (7 * 24 + 1))
    by_start = {r.period_start: r for r in rs}
    assert local_hour(by_start[first], HELSINKI) == 3
    assert local_hour(by_start[second], HELSINKI) == 3
    b = fit_baseline(clean(rs), HELSINKI, rs[-1].period_end + timedelta(hours=1))
    assert b is not None
    assert b.counts[3] == 8
    assert all(b.counts[h] == 7 for h in range(24) if h != 3)
    # spring forward 2026-03-29 03:00 EET -> 04:00 EEST: local 03:00 is skipped (7 local days - 1 h)
    rs = hourly(datetime(2026, 3, 25, 23, tzinfo=UTC), [5.0] * (7 * 24 - 1))
    b = fit_baseline(clean(rs), HELSINKI, rs[-1].period_end + timedelta(hours=1))
    assert b.counts[3] == 6
    assert all(b.counts[h] == 7 for h in range(24) if h != 3)
    assert b.expected(3)[1] == params.MAD_FLOOR


def weekly_typical_bands(location_id, tz):
    checked = validate(sample_readings(location_id))
    first, last = checked[0].reading.period_end, checked[-1].reading.period_end
    bands = []
    as_of = first + timedelta(days=14)
    while as_of <= last + timedelta(hours=1):
        b = fit_baseline(checked, tz, as_of)
        if b is not None:
            bands.append(b.typical_band)
        as_of += timedelta(days=7)
    return Counter(bands)


def test_qa_det_02_typical_band():
    # The station's typical band is its most common weekly 14-day typical band across the sample.
    delhi = weekly_typical_bands(4712609, ZoneInfo("Asia/Kolkata"))
    helsinki = weekly_typical_bands(4588, HELSINKI)
    assert delhi.most_common(1)[0][0] is Band.USG
    assert helsinki.most_common(1)[0][0] is Band.GOOD
