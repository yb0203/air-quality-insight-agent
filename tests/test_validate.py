from datetime import datetime, timedelta

from aqagent.sense.validate import gap_breaks, validate
from aqagent.types import Reading, ReasonCode
from tests.fixtures import UTC, hourly

T0 = datetime(2026, 9, 1, 1, tzinfo=UTC)


def codes(checked):
    return [c.excluded for c in checked]


def test_qa_dq_01_invalid():
    rs = hourly(T0, [10, -1, 12, 1200, 11])
    out = validate(rs, provisional_last=False)
    assert codes(out) == [None, ReasonCode.DQ_INVALID, None, ReasonCode.DQ_INVALID, None]
    assert [c.reading for c in out] == rs  # kept as evidence


def test_qa_dq_01_none_value_is_invalid():
    rs = [Reading(1, T0, T0 - timedelta(hours=1), None, 100.0)] + hourly(T0 + timedelta(hours=1), [10])
    assert codes(validate(rs, provisional_last=False)) == [ReasonCode.DQ_INVALID, None]


def test_qa_dq_02_low_coverage():
    rs = hourly(T0, [10, 11]) + hourly(T0 + timedelta(hours=2), [12], coverage=60.0) + hourly(T0 + timedelta(hours=3), [11])
    out = validate(rs, provisional_last=False)
    assert codes(out) == [None, None, ReasonCode.DQ_LOW_COVERAGE, None]
    assert hourly(T0, [10], coverage=75.0)[0].coverage_pct == 75.0
    assert codes(validate(hourly(T0, [10, 11], coverage=75.0), provisional_last=False)) == [None, None]


def test_qa_dq_03_stuck():
    out = validate(hourly(T0, [5, 7, 7, 7, 7, 7, 7, 9]), provisional_last=False)
    assert codes(out) == [None] + [ReasonCode.DQ_STUCK] * 6 + [None]


def test_qa_dq_03_five_identical_is_not_stuck():
    out = validate(hourly(T0, [5, 7, 7, 7, 7, 7, 9]), provisional_last=False)
    assert ReasonCode.DQ_STUCK not in codes(out)


def test_qa_dq_03_stuck_needs_consecutive_hours():
    vals = [7, 7, 7, None, 7, 7, 7]  # a missing hour breaks the run
    assert ReasonCode.DQ_STUCK not in codes(validate(hourly(T0, vals), provisional_last=False))


def test_qa_dq_04_glitch_mumbai():
    out = validate(hourly(T0, [75, 980, 90]))
    assert codes(out) == [None, ReasonCode.DQ_SUSPECT, None]


def test_qa_dq_04_real_rise_is_not_a_glitch():
    # stays high afterwards -> not isolated
    assert ReasonCode.DQ_SUSPECT not in codes(validate(hourly(T0, [75, 980, 900])))
    # tiny absolute jump (+6) -> below GLITCH_DELTA
    assert ReasonCode.DQ_SUSPECT not in codes(validate(hourly(T0, [1, 7, 1])))


def test_qa_dq_05_provisional_last():
    out = validate(hourly(T0, [30, 200]))
    assert out[-1].provisional is True and out[-1].excluded is None
    assert out[0].provisional is False
    out = validate(hourly(T0, [30, 200, 30]))
    assert out[1].excluded is ReasonCode.DQ_SUSPECT and out[1].provisional is False
    assert out[2].provisional is True


def test_qa_dq_05_provisional_off():
    out = validate(hourly(T0, [30, 200]), provisional_last=False)
    assert [c.provisional for c in out] == [False, False]


def test_validate_sorts_and_keeps_last_duplicate():
    rs = hourly(T0, [10, 11, 12])
    revised = Reading(1, rs[1].period_end, rs[1].period_start, 99.0, 100.0)
    out = validate([rs[2], rs[1], rs[0], revised], provisional_last=False)
    assert [c.reading.period_end for c in out] == [r.period_end for r in rs]
    assert out[1].reading.value == 99.0


def test_qa_dq_08_gap_breaks():
    vals = [10, 10, None, None, None, None, 10, 10]  # 4 missing hours
    rs = hourly(T0, vals)
    assert gap_breaks(rs) == {T0 + timedelta(hours=6)}
    three_missing = hourly(T0, [10, None, None, None, 10])
    assert gap_breaks(three_missing) == set()
    assert gap_breaks([]) == set()
