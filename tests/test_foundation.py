import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aqagent import params
from aqagent.clock import FixedClock
from aqagent.types import Band, ReasonCode


def test_params_match_spec():
    assert (params.SPIKE_Z, params.CLIMB_BAR, params.ELEVATED_H, params.CALM_HOURS) == (3.5, 1.26, 8, 4)
    assert params.SENSITIVITY_K == {"low": 1.25, "default": 1.0, "high": 0.75}
    assert (params.PACE_BASE_HOURS, params.BUDGET_PER_DAY, params.NO_DATA_TIMEOUT_HOURS) == (6, 3, 24)
    assert (params.CLIMB_SLOPE, params.FLAP_HOURS, params.CLEAR_MIN_HOURS) == (0.01, 6, 12)


def test_band_order_and_severity():
    assert Band.VERY_UNHEALTHY > Band.UNHEALTHY
    assert Band.VERY_UNHEALTHY.is_severe and not Band.UNHEALTHY.is_severe
    assert Band.parse("usg") is Band.USG
    assert Band.HAZARDOUS.slug == "hazardous"


def test_reason_codes_include_spec_vocabulary():
    for code in ["NO_DATA", "LATE_HOUR_SCORED", "ARBITRATED_OUT", "DAILY_BUDGET", "NO_DATA_TIMEOUT", "SENT_CHECK_IN"]:
        assert ReasonCode(code).value == code


def test_fixed_clock_advances():
    t = datetime(2026, 10, 18, 6, 20, tzinfo=timezone.utc)
    c = FixedClock(t)
    c.advance(timedelta(hours=1))
    assert c.now() == t + timedelta(hours=1)


def test_qa_eval_05_no_wall_clock_in_src():
    pattern = re.compile(r"datetime\.(now|utcnow)\(|time\.time\(|date\.today\(")
    offenders = [p for p in Path("src/aqagent").rglob("*.py") if p.name != "clock.py" and pattern.search(p.read_text())]
    assert offenders == []
