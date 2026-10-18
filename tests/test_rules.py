from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from aqagent.decide.rules import load_rules
from aqagent.types import Band, ReasonCode

DELHI = 4712609
HELSINKI = 4588
UTC = timezone.utc
HEL = ZoneInfo("Europe/Helsinki")
KOLKATA = ZoneInfo("Asia/Kolkata")
USERS_YAML = Path(__file__).resolve().parent.parent / "config" / "users.yaml"


def test_qa_rule_01_defaults():
    rules, reason = load_rules(None, None, default_station=DELHI)
    assert reason is None
    assert rules.location.station_id == DELHI
    assert rules.pollutants == ["pm25"]
    assert rules.sensitivity == "default"
    assert rules.k == 1.0
    assert rules.relevance_floor is Band.MODERATE
    assert rules.alert_band is Band.VERY_UNHEALTHY
    assert (rules.quiet_hours.start, rules.quiet_hours.end) == (time(22, 0), time(7, 0))
    assert rules.quiet_hours.breakthrough_band is Band.VERY_UNHEALTHY
    assert rules.check_in.cron is None
    assert rules.pace.base_gap_hours == 6
    assert rules.budget.max_per_day == 3


def test_qa_rule_01_missing_fields_fall_back_to_defaults():
    rules, reason = load_rules({"location": {"station_id": HELSINKI}, "sensitivity": "low"}, None)
    assert reason is None
    assert rules.location.station_id == HELSINKI
    assert rules.k == 1.25
    assert rules.quiet_hours.start == time(22, 0)


def test_qa_rule_01_no_station_anywhere_is_an_error():
    with pytest.raises(ValueError):
        load_rules(None, None)


@pytest.mark.parametrize(
    "bad",
    [
        {"location": {"station_id": HELSINKI}, "colour": "blue"},
        {"location": {"station_id": HELSINKI}, "quiet_hours": {"start": "22:00", "snooze": True}},
        {"location": {"station_id": HELSINKI}, "alert_band": "purple"},
        {"location": {"station_id": HELSINKI}, "relevance_floor": 3},
        {"location": {"station_id": HELSINKI}, "alert_band": "Very Unhealthy"},
        {"location": {"station_id": HELSINKI}, "check_in": {"cron": "61 6 * * *"}},
        {"location": {"station_id": HELSINKI}, "check_in": {"cron": "30 6 * *"}},
        {"location": {"station_id": HELSINKI}, "quiet_hours": {"start": "25:00"}},
        {"location": {"station_id": HELSINKI}, "sensitivity": "extreme"},
    ],
)
def test_qa_rule_02_invalid_falls_back(bad):
    previous, _ = load_rules({"location": {"station_id": DELHI}, "sensitivity": "high"}, None)
    rules, reason = load_rules(bad, previous)
    assert reason is ReasonCode.RULES_INVALID
    assert rules is previous


def test_qa_rule_02_invalid_without_previous_uses_defaults():
    rules, reason = load_rules({"location": {"station_id": HELSINKI}, "alert_band": "purple"}, None)
    assert reason is ReasonCode.RULES_INVALID
    assert rules.location.station_id == HELSINKI
    assert rules.alert_band is Band.VERY_UNHEALTHY


def test_high_sensitivity_alert_band_default():
    rules, _ = load_rules({"location": {"station_id": HELSINKI}, "sensitivity": "high"}, None)
    assert rules.alert_band is Band.UNHEALTHY
    assert rules.k == 0.75
    explicit, _ = load_rules({"location": {"station_id": HELSINKI}, "sensitivity": "high", "alert_band": "hazardous"}, None)
    assert explicit.alert_band is Band.HAZARDOUS


def test_bands_accept_every_slug_and_serialise_back():
    for band in Band:
        rules, reason = load_rules({"location": {"station_id": DELHI}, "relevance_floor": band.slug}, None)
        assert reason is None and rules.relevance_floor is band
    rules, _ = load_rules(
        {
            "location": {"station_id": DELHI},
            "relevance_floor": "usg",
            "quiet_hours": {"start": "23:30", "end": "06:00"},
            "check_in": {"cron": "30 6 * * *"},
        },
        None,
    )
    dumped = rules.model_dump(mode="json")
    assert dumped["relevance_floor"] == "usg"
    assert dumped["alert_band"] == "very_unhealthy"
    assert dumped["quiet_hours"] == {"start": "23:30", "end": "06:00", "breakthrough_band": "very_unhealthy"}
    again, reason = load_rules(dumped, None)
    assert reason is None and again == rules


def test_quiet_hours_cross_midnight():
    rules, _ = load_rules(None, None, default_station=DELHI)  # 22:00-07:00

    def at(h, m=0):
        return datetime(2026, 10, 18, h, m, tzinfo=KOLKATA)

    assert [rules.in_quiet_hours(at(h)) for h in (21, 22, 23, 0, 3, 6)] == [False, True, True, True, True, True]
    assert rules.in_quiet_hours(at(6, 59)) and not rules.in_quiet_hours(at(7)) and not rules.in_quiet_hours(at(12))
    same_day, _ = load_rules({"location": {"station_id": DELHI}, "quiet_hours": {"start": "13:00", "end": "15:00"}}, None)
    assert same_day.in_quiet_hours(at(13)) and not same_day.in_quiet_hours(at(15)) and not same_day.in_quiet_hours(at(23))
    empty, _ = load_rules({"location": {"station_id": DELHI}, "quiet_hours": {"start": "07:00", "end": "07:00"}}, None)
    assert not any(empty.in_quiet_hours(at(h)) for h in range(24))


def test_quiet_end_after_is_the_next_local_end():
    rules, _ = load_rules(None, None, default_station=DELHI)
    assert rules.quiet_end_after(datetime(2026, 10, 18, 3, 0, tzinfo=KOLKATA)) == datetime(2026, 10, 18, 7, 0, tzinfo=KOLKATA)
    assert rules.quiet_end_after(datetime(2026, 10, 18, 23, 0, tzinfo=KOLKATA)) == datetime(2026, 10, 19, 7, 0, tzinfo=KOLKATA)
    assert rules.quiet_end_after(datetime(2026, 10, 18, 7, 0, tzinfo=KOLKATA)) == datetime(2026, 10, 19, 7, 0, tzinfo=KOLKATA)
    with pytest.raises(ValueError):
        rules.quiet_end_after(datetime(2026, 10, 18, 3, 0))


def test_qa_rule_10_quiet_hours_follow_wall_clock_across_helsinki_dst():
    rules, _ = load_rules(None, None, default_station=HELSINKI)
    # 2026-10-25 04:00 EEST -> 03:00 EET: that night's window is 10 real hours, still 22:00-07:00 on the wall.
    start = datetime(2026, 10, 24, 22, 0, tzinfo=HEL)
    end = rules.quiet_end_after(start)
    assert (end.hour, end.minute) == (7, 0)
    assert end.astimezone(UTC) == datetime(2026, 10, 25, 5, 0, tzinfo=UTC)
    assert start.astimezone(UTC) == datetime(2026, 10, 24, 19, 0, tzinfo=UTC)
    assert rules.in_quiet_hours(datetime(2026, 10, 25, 1, 0, tzinfo=UTC).astimezone(HEL))  # the repeated 03:00-04:00
    assert not rules.in_quiet_hours(datetime(2026, 10, 25, 5, 0, tzinfo=UTC).astimezone(HEL))


def test_qa_rule_10_next_check_in_across_helsinki_dst():
    rules, _ = load_rules({"location": {"station_id": HELSINKI}, "check_in": {"cron": "30 6 * * *"}}, None)
    before = rules.next_check_in(datetime(2026, 10, 23, 12, 0, tzinfo=UTC), HEL)
    assert before == datetime(2026, 10, 24, 3, 30, tzinfo=UTC)  # 06:30 EEST (UTC+3)
    assert before.utcoffset().total_seconds() == 0
    after = rules.next_check_in(before, HEL)  # strictly after: never the same instant again
    assert after == datetime(2026, 10, 25, 4, 30, tzinfo=UTC)  # 06:30 EET (UTC+2)
    assert rules.next_check_in(after, "Europe/Helsinki") == datetime(2026, 10, 26, 4, 30, tzinfo=UTC)


def test_qa_rule_10_next_check_in_delhi_half_hour_offset_and_none():
    rules, _ = load_rules({"location": {"station_id": DELHI}, "check_in": {"cron": "30 6 * * *"}}, None)
    assert rules.next_check_in(datetime(2026, 10, 18, 0, 0, tzinfo=UTC), KOLKATA) == datetime(2026, 10, 18, 1, 0, tzinfo=UTC)
    plain, _ = load_rules(None, None, default_station=DELHI)
    assert plain.next_check_in(datetime(2026, 10, 18, tzinfo=UTC), KOLKATA) is None


def test_qa_rule_11_resolve():
    from aqagent.sense.resolve import station_for

    delhi, _ = load_rules({"location": {"station_id": DELHI}}, None)
    helsinki, _ = load_rules({"location": {"station_id": HELSINKI}}, None)
    assert station_for(delhi) == DELHI
    assert station_for(helsinki) == HELSINKI


def test_demo_users_load():
    from aqagent.decide.rules import Rules, load_users

    users = load_users(USERS_YAML)
    assert [u.id for u in users] == ["arjun", "meera", "priya", "omar", "maya", "aino"]
    assert all(isinstance(u.rules, Rules) for u in users)
    by_id = {u.id: u for u in users}
    expected = {
        "arjun": ("Delhi", 4712609, "default", "30 6 * * *"),
        "meera": ("Delhi", 4712609, "high", None),
        "priya": ("Bengaluru", 6206921, "default", "0 6 * * *"),
        "omar": ("Dubai", 6096447, "low", None),
        "maya": ("Los Angeles", 7936, "default", None),
        "aino": ("Helsinki", 4588, "high", None),
    }
    for uid, (city, station, sensitivity, cron) in expected.items():
        u = by_id[uid]
        assert (u.city, u.rules.location.station_id, u.rules.sensitivity, u.rules.check_in.cron) == (city, station, sensitivity, cron)
        assert u.display_name
    assert "asthma" in by_id["meera"].persona.conditions and "asthma" in by_id["aino"].persona.conditions
    assert "morning run 06:30" in by_id["arjun"].persona.habits
    assert "morning run 06:00" in by_id["priya"].persona.habits
    assert by_id["aino"].rules.alert_band is Band.UNHEALTHY


def test_demo_users_reject_bad_rules(tmp_path):
    from aqagent.decide.rules import load_users

    bad = tmp_path / "users.yaml"
    bad.write_text(
        "users:\n  - id: x\n    display_name: X\n    city: Delhi\n    persona: {conditions: [], habits: []}\n"
        "    rules: {location: {station_id: 1}, alert_band: purple}\n"
    )
    with pytest.raises(ValueError):
        load_users(bad)
