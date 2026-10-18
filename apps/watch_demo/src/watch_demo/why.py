"""Turn the agent's decision records into short lines a person can read at a glance."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import Decision, Explain, Notification, User

# Used only when /users has no `timezone` for a person.
CITY_TIMEZONES = {
    "Helsinki": "Europe/Helsinki",
    "Los Angeles": "America/Los_Angeles",
    "Bengaluru": "Asia/Kolkata",
    "Delhi": "Asia/Kolkata",
    "Mumbai": "Asia/Kolkata",
    "Dubai": "Asia/Dubai",
}

BAND_LABELS = {
    "good": "Good",
    "moderate": "Moderate",
    "usg": "Unhealthy for sensitive groups",
    "unhealthy": "Unhealthy",
    "very_unhealthy": "Very unhealthy",
    "hazardous": "Hazardous",
}


def user_tz(user: User) -> ZoneInfo:
    return ZoneInfo(user.timezone or CITY_TIMEZONES.get(user.city, "UTC"))


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def clock(value: Any, tz: ZoneInfo) -> str:
    """'1am', '6:30am', '5pm' in the person's local time."""
    t = _parse(value)
    if t is None:
        return ""
    t = t.astimezone(tz)
    hour = t.hour % 12 or 12
    suffix = "am" if t.hour < 12 else "pm"
    return f"{hour}{suffix}" if t.minute == 0 else f"{hour}:{t.minute:02d}{suffix}"


def part_of_day(t: datetime, tz: ZoneInfo) -> str:
    h = t.astimezone(tz).hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "evening"
    return "night"


def relative(t: datetime, now: datetime) -> str:
    minutes = int((now - t).total_seconds() // 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return "yesterday" if hours < 48 else f"{hours // 24}d ago"


def _values(ex: Explain, layer: str) -> dict[str, Any]:
    entry = ex.layer(layer)
    return entry.values if entry else {}


def _latest_score(ex: Explain) -> dict[str, Any]:
    scores = [s for s in ex.scores if s.get("pm25") is not None or s.get("nowcast") is not None]
    if scores:
        return max(scores, key=lambda s: str(s.get("at", "")))
    return _values(ex, "U2")


def _num(x: Any) -> str:
    return f"{float(x):.0f}"


def why_lines(n: Notification, ex: Explain, user: User) -> list[str]:
    """Three or four plain-English lines: what happened, how unusual, why now, why you."""
    tz = user_tz(user)
    d1, d2, d3, d4 = (_values(ex, k) for k in ("D1", "D2", "D3", "D4"))
    d7, d8 = _values(ex, "D7"), _values(ex, "D8")
    score = _latest_score(ex)
    lines: list[str] = []

    # 1. What happened, in story terms.
    started = d2.get("started_at")
    if n.kind == "cleared":
        hours, ended = d2.get("hours"), d2.get("ended_at")
        if hours and started and ended:
            lines.append(f"Bad for {_num(hours)} hours, {clock(started, tz)} to {clock(ended, tz)}")
    elif started:
        lead = {
            "climb": "Climbing since",
            "spike": "Jumped sharply at",
            "elevated": "Stuck above normal since",
            "floor": f"Crossed into {BAND_LABELS.get(n.band, n.band)} at",
        }.get(n.event_kind or "", "Started")
        lines.append(f"{lead} {clock(started, tz)}")

    # 2. How unusual, against this place's own normal.
    now_pm, usual = score.get("pm25") or score.get("nowcast"), score.get("typical_pm25")
    when = part_of_day(ex.decision.evaluated_at, tz)
    peak = d2.get("peak") or {}
    if n.kind == "cleared" and now_pm is not None and peak.get("pm25"):
        lines.append(f"Down to {_num(now_pm)} from a peak of {_num(peak['pm25'])} at {clock(peak.get('at'), tz)}")
    elif now_pm is not None and usual:
        ratio = float(now_pm) / float(usual)
        if ratio >= 3:
            lines.append(f"About {ratio:.0f}× a usual {user.city} {when} ({_num(now_pm)} vs {_num(usual)})")
        elif ratio >= 1.5:
            lines.append(f"Well above a normal {user.city} {when}")
        else:
            lines.append(f"A little above a normal {user.city} {when}")

    # 3. Why it arrived when it did.
    check_in = d8.get("check_in")
    if n.kind == "check_in" and d8.get("absorbed_held"):
        lines.append(f"Held overnight (quiet hours), sent at your {check_in} check-in")
    elif n.kind == "check_in":
        lines.append(f"Sent at your {check_in} check-in")
    elif n.kind == "released":
        lines.append("Held overnight (quiet hours), sent when they ended")
    elif d4.get("elapsed_h") is not None:
        lines.append(f"{float(d4['elapsed_h']):g} hours since your last message")

    # 4. Why it was worth your attention.
    sensitivity = d1.get("sensitivity")
    if sensitivity == "high":
        lines.append("Your high sensitivity lowers the bar")
    elif sensitivity == "low":
        lines.append("Your low sensitivity raises the bar, and this still cleared it")
    elif n.kind == "cleared" and d3.get("lasted_h") and d3.get("min_hours"):
        lines.append(f"Long enough (over {_num(d3['min_hours'])}h) to be worth an all-clear")
    if d7.get("sent_today") == 0 and len(lines) < 4:
        lines.append("Your first message today")

    return lines[:4]


# Most informative first: what a person would most want to know about a silence.
_SILENCE = [
    ("DQ_SUSPECT", "A 1-hour sensor glitch was ignored"),
    ("DQ_INVALID", "An impossible reading was ignored"),
    ("DQ_STUCK", "A stuck sensor reading was ignored"),
    ("QUIET_HOURS_HELD", "Something is being held until morning"),
    ("HELD_EXPIRED", "It cleared up overnight before you needed to know"),
    ("DAILY_BUDGET", "You've had enough messages for today"),
    ("COOLDOWN", "Too soon after the last message"),
    ("DEDUP_SAME_BAND", "No change since the last message"),
    ("RECOVERY_NOT_WORTH_SAYING", "A short blip that has already passed"),
    ("BELOW_RELEVANCE", "Unusual, but the air stayed good"),
    ("CHECKIN_QUIET", "Your {check_in} check-in found nothing worth saying"),
    ("NO_DATA", "The sensor has been quiet for a while"),
]


def silence_line(decisions: list[Decision], user: User) -> str | None:
    """One line on why nothing was sent, from the decisions in the window."""
    if not decisions:
        return None
    by_code = {d.reason_code: d for d in decisions}
    for code, text in _SILENCE:
        if code in by_code:
            if "{check_in}" in text:
                local = by_code[code].evaluated_at.astimezone(user_tz(user))
                return text.format(check_in=local.strftime("%H:%M"))
            return text
    hours = round((max(d.evaluated_at for d in decisions) - min(d.evaluated_at for d in decisions)).total_seconds() / 3600)
    return f"Watched {hours} hours: nothing unusual for {user.city}"
