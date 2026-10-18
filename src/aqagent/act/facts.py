"""A1 COMPOSE, part 1: turn a decision into verified facts (S-C §9). Pure and deterministic.

The composer (LLM or template) only ever sees what `build_insight` returns.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aqagent import params
from aqagent.types import Band, Candidate, CandidateKind, StationScore
from aqagent.understand.aqi import aqi_value, band_for

# ---------------------------------------------------------------- action catalogue
# Short imperative phrases. Within one list no phrase is a substring of another, so the validator can count
# "exactly one action". Phrases containing the word "run" are habit actions, kept only for runners.

_FRESH = ["go for that run", "open the windows", "spend some time outside"]
_BAD_AIR = {
    Band.GOOD: _FRESH,
    Band.MODERATE: ["keep the run short and easy", "take it easy outdoors", "keep windows closed"],
    Band.USG: ["move the run indoors", "keep windows closed", "limit long outdoor exertion"],
    Band.UNHEALTHY: ["skip the outdoor run", "keep windows closed", "wear an N95 outside"],
    Band.VERY_UNHEALTHY: ["skip the outdoor run", "stay indoors with windows closed", "wear an N95 outside"],
    Band.HAZARDOUS: ["skip the outdoor run", "stay indoors with windows closed", "switch on an air purifier if you have one"],
}
_CLEARED = {
    Band.GOOD: _FRESH,
    Band.MODERATE: _FRESH,
    Band.USG: ["go for an easy run", "air out the house for a bit", "take a short walk outside"],
    Band.UNHEALTHY: ["go for an easy run", "air out the house for a bit", "take a short walk outside"],
    Band.VERY_UNHEALTHY: ["keep windows closed", "wear an N95 outside"],
    Band.HAZARDOUS: ["keep windows closed", "wear an N95 outside"],
}

ACTION_CATALOGUE: dict[tuple[CandidateKind, Band], list[str]] = {
    (kind, band): list((_CLEARED if kind is CandidateKind.cleared else _BAD_AIR)[band])
    for kind in CandidateKind
    for band in Band
}

_RUN_WORD = re.compile(r"\brun\b", re.IGNORECASE)
_RUN_HABIT = re.compile(r"\b(run|running|jog|jogging)\b", re.IGNORECASE)
_HABIT_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _run_habit_hour(persona: dict) -> tuple[bool, int | None]:
    """(has a run habit, its local hour if stated)."""
    for habit in persona.get("habits") or []:
        if _RUN_HABIT.search(habit):
            m = _HABIT_TIME.search(habit)
            return True, int(m.group(1)) if m else None
    return False, None


def action_candidates(kind: CandidateKind, band: Band, persona: dict, local_hour: int) -> list[str]:
    """Catalogue actions for (kind, band), filtered by persona habit and local hour; habit actions first.

    A run action is kept only for a runner, and, when the air is bad, only while today's run is still ahead
    (local hour ≤ the run's hour). After a clearing it's kept whenever the person runs.
    """
    is_runner, run_hour = _run_habit_hour(persona or {})
    habit, generic = [], []
    for action in ACTION_CATALOGUE[(kind, band)]:
        if not _RUN_WORD.search(action):
            generic.append(action)
            continue
        if not is_runner:
            continue
        if kind is CandidateKind.cleared or run_hour is None or local_hour <= run_hour:
            habit.append(action)
    return habit + generic


# ---------------------------------------------------------------- formatting

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")
_PARTS = (  # (name, first local hour, last local hour); night wraps midnight
    ("morning", 5, 11),
    ("afternoon", 12, 16),
    ("evening", 17, 21),
)
_DAYS_IN_WEEK = 7
_HOURS_PER_DAY = 24
_DAYS_WORDING_FROM_HOURS = 48


def fmt_date(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]}"


def fmt_hour(local: datetime) -> str:
    """'2am', '12pm', '6:30am'."""
    h12 = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    return f"{h12}{suffix}" if local.minute == 0 else f"{h12}:{local.minute:02d}{suffix}"


def part_of_day(local: datetime) -> tuple[str, date]:
    """Part-of-day name and the date it belongs to (the small hours belong to the previous night)."""
    for name, lo, hi in _PARTS:
        if lo <= local.hour <= hi:
            return name, local.date()
    if local.hour < _PARTS[0][1]:
        return "night", local.date() - timedelta(days=1)
    return "night", local.date()


def _as_dt(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _is_bad(s: StationScore) -> bool:
    """Bad = at least Moderate and above what's typical for this station."""
    if s.band is None or s.band < Band.MODERATE:
        return False
    return s.typical_band is None or s.band > s.typical_band


def _hours_phrase(hours: int) -> str:
    if hours >= _DAYS_WORDING_FROM_HOURS:
        return f"{hours // _HOURS_PER_DAY} days"
    return "1 hour" if hours == 1 else f"{hours} hours"


# ---------------------------------------------------------------- history facts


def history_facts(
    history: list[StationScore],
    at: datetime,
    tz: ZoneInfo,
    episode: dict | None,
    *,
    kind: CandidateKind | None = None,
) -> list[str]:
    """Deterministic past-context phrases, most story-like first.

    - "back to its usual level after N hours" (cleared only)
    - "since <local hour>" (the episode's start; a date when it began over a day ago)
    - "worst since <date>": the spell's peak, compared with everything before the spell
    - "Nth bad <part of day> this week"
    """
    known = sorted((s for s in history if s.period_end <= at), key=lambda s: s.period_end)
    facts: list[str] = []
    opened = _as_dt(episode.get("opened_at")) if episode else None

    if kind is CandidateKind.cleared:
        if episode and episode.get("hours"):
            facts.append(f"back to its usual level after {_hours_phrase(int(episode['hours']))}")
    elif opened is not None:
        if at - opened < timedelta(hours=_HOURS_PER_DAY):
            facts.append(f"since {fmt_hour(opened.astimezone(tz))}")
        else:
            facts.append(f"since {fmt_date(opened.astimezone(tz).date())}")

    if not known:
        return facts
    current = known[-1]

    # worst since <date>
    spell_start = opened if opened is not None else current.period_end
    spell = [s.nowcast for s in known if s.period_end >= spell_start and s.nowcast is not None]
    peak = max(spell + ([float(episode["peak_value"])] if episode and episode.get("peak_value") is not None else []),
               default=None)
    if peak is not None and band_for(peak) >= Band.MODERATE and (current.typical_band is None or band_for(peak) > current.typical_band):
        today = at.astimezone(tz).date()
        before = [s for s in known if s.period_end < spell_start and s.nowcast is not None]
        higher = [s for s in before if s.nowcast >= peak]
        if higher:
            d = higher[-1].period_end.astimezone(tz).date()
            if d < today:
                facts.append(f"worst since {fmt_date(d)}")
        elif before:
            span = (today - before[0].period_end.astimezone(tz).date()).days
            if span >= 2:
                facts.append(f"worst in {span} days")

    # Nth bad <part> this week
    if kind is not CandidateKind.cleared and _is_bad(current):
        part, key = part_of_day(at.astimezone(tz))
        earliest = key - timedelta(days=_DAYS_IN_WEEK - 1)
        days = set()
        for s in known:
            p, k = part_of_day(s.period_end.astimezone(tz))
            if p == part and earliest <= k <= key and _is_bad(s):
                days.add(k)
        n = len(days)
        if 2 <= n <= len(_ORDINALS):
            facts.append(f"{_ORDINALS[n - 1]} bad {part} this week")

    return facts


# ---------------------------------------------------------------- insight


def _trend(score: StationScore, known: list[StationScore]) -> dict | None:
    if score.slope_6h is None:
        return None
    if score.slope_6h >= params.CLIMB_SLOPE:
        direction = "rising"
    elif score.slope_6h <= -params.CLIMB_SLOPE:
        direction = "falling"
    else:
        direction = "steady"
    per_hour = None
    then = score.period_end - timedelta(hours=params.SLOPE_HOURS)
    past = [s for s in known if s.period_end == then and s.nowcast is not None]
    if past and score.nowcast is not None:
        per_hour = round((score.nowcast - past[0].nowcast) / params.SLOPE_HOURS, 1)
    return {"direction": direction, "per_hour": per_hour}


def build_insight(
    candidate: Candidate,
    *,
    user: dict,
    city: str,
    tz: ZoneInfo,
    at: datetime,
    score: StationScore,
    typical_pm25: float | None,
    episode: dict | None,
    history: list[StationScore],
    absorbed_held: list[Candidate],
) -> dict:
    """The S-C §9 structured insight: the only input A1 composes from."""
    local = at.astimezone(tz)
    known = sorted({s.period_end: s for s in [*history, score] if s.period_end <= at}.values(),
                   key=lambda s: s.period_end)
    band = score.band if score.band is not None else (candidate.band if candidate.band is not None else Band.GOOD)
    persona = user.get("persona") or {}

    facts = history_facts(known, at, tz, episode, kind=candidate.kind)
    if not facts and score.typical_band is not None and band > score.typical_band:
        facts.append(f"worse than a usual {part_of_day(local)[0]}")

    ep = None
    if episode:
        opened = _as_dt(episode.get("opened_at"))
        peak_at = _as_dt(episode.get("peak_at"))
        peak_band = episode.get("peak_band")
        ep = {
            "started": f"since {fmt_hour(opened.astimezone(tz))}" if opened else None,
            "hours": episode.get("hours"),
            "peak": {
                "pm25": round(episode["peak_value"]) if episode.get("peak_value") is not None else None,
                "band": Band.parse(peak_band).slug if peak_band is not None else None,
                "at": fmt_hour(peak_at.astimezone(tz)) if peak_at else None,
            },
        }

    kind = "released_after_quiet_hours" if candidate.kind is CandidateKind.released else candidate.kind.value
    return {
        "kind": kind,
        "event_kind": candidate.event_kind.value if candidate.event_kind else None,
        "city": city,
        "local_time": local.isoformat(timespec="minutes"),
        "now": {
            "pm25": round(score.nowcast) if score.nowcast is not None else None,
            "band": band.slug,
            "aqi": aqi_value(score.nowcast) if score.nowcast is not None else None,
        },
        "typical_for_this_hour": {
            "pm25": round(typical_pm25) if typical_pm25 is not None else None,
            "band": score.typical_band.slug if score.typical_band is not None else None,
        },
        "episode": ep,
        "absorbed_held": [
            {"kind": c.kind.value, "band": c.band.slug if c.band is not None else None,
             "event_kind": c.event_kind.value if c.event_kind else None}
            for c in absorbed_held
        ],
        "history_facts": facts,
        "trend": _trend(score, known),
        "user": {"name": user.get("name"), "persona": persona},
        "action_candidates": action_candidates(candidate.kind, band, persona, local.hour),
    }
