import pytest

from aqagent.types import Band
from aqagent.understand.aqi import aqi_value, band_for, nowcast


@pytest.mark.parametrize(
    "c,band",
    [(9.0, "good"), (9.1, "moderate"), (35.4, "moderate"), (35.5, "usg"), (55.4, "usg"),
     (55.5, "unhealthy"), (125.4, "unhealthy"), (125.5, "very_unhealthy"), (225.4, "very_unhealthy"),
     (225.5, "hazardous"), (9.04, "good")],
)
def test_qa_ing_10_band_boundaries(c, band):
    assert band_for(c) is Band.parse(band)


def test_qa_ing_11_nowcast_validity():
    assert nowcast([(2, 10.0), (5, 10.0)]) is None  # only 1 of the 3 most recent hours is valid
    assert nowcast([(0, 10.0), (2, 10.0)]) == pytest.approx(10.0)


def test_qa_ing_11_nowcast_weighting():
    w = [(0, 100.0)] + [(h, 10.0) for h in range(1, 12)]  # (max-min)/max = 0.9 -> w clamped to 0.5
    expected = sum(0.5**h * c for h, c in w) / sum(0.5**h for h, _ in w)
    assert nowcast(w) == pytest.approx(expected, abs=0.1)
    steady = [(h, 20.0) for h in range(12)]  # w = 1 -> plain average
    assert nowcast(steady) == pytest.approx(20.0)


def test_qa_ing_11_nowcast_ignores_hours_beyond_12():
    assert nowcast([(0, 10.0), (1, 10.0), (13, 500.0)]) == pytest.approx(10.0)


def test_aqi_value_breakpoints():
    assert aqi_value(9.0) == 50
    assert aqi_value(35.5) == 101
    assert aqi_value(0.0) == 0
    assert aqi_value(500.0) >= 301
