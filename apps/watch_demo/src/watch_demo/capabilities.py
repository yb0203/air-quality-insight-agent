"""Plain-English names for what the agent can do, and for what it decided.

Scenarios tag themselves with capability keys; the page turns those into labelled tags,
and turns each decision's reason code and trace into a sentence and a layer path.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Decision, TraceEntry


@dataclass(frozen=True)
class Capability:
    label: str
    brief: str  # the brief requirement it answers
    what: str  # one line for the capabilities page


CAPABILITIES: dict[str, Capability] = {
    "climb": Capability("climb trend", "B2a", "Notices air that keeps getting worse for hours, not one bad reading."),
    "spike": Capability("sudden spike", "B2b", "Notices a sharp jump against this place's normal for the hour."),
    "elevated": Capability("slow build-up", "B2a", "Catches air stuck a little above normal for a long time."),
    "clearing": Capability("back to normal", "B2c", "Says so when a genuinely bad spell is over."),
    "quiet-clear": Capability("no needless all-clear", "B2c", "Skips the all-clear after a short, mild spell."),
    "baseline": Capability("learned normal", "B2", "Judges each city against its own usual level for that hour."),
    "glitch": Capability("glitch filter", "B2d", "Ignores one-hour sensor glitches instead of raising an alarm."),
    "missed": Capability("missed-trigger guard", "B2d", "Logs near-misses and slow drifts so quiet build-ups aren't missed."),
    "no-repeats": Capability("no repeats", "B3", "One bad spell is one story: no second message unless it's a band worse."),
    "pace": Capability("pacing", "BX1", "Waits longer between messages in the same story: 6, then 12, then 24 hours."),
    "budget": Capability("daily budget", "BX1", "At most three non-severe messages a day."),
    "quiet-hours": Capability("quiet hours", "D8", "Holds messages overnight and sends them as one in the morning."),
    "check-in": Capability("morning check-in", "D8", "Speaks at the person's chosen time if the air is worse than usual."),
    "severe": Capability("severe breaks through", "D8", "Very unhealthy air is sent at once, even at night."),
    "sensitivity": Capability("personal sensitivity", "B5", "A sensitive person gets a lower bar; the facts stay the same."),
    "message": Capability("one clear action", "B4", "Short, with past context and exactly one thing to do."),
    "no-data": Capability("silent sensor", "B1", "Says nothing it can't back up when a sensor goes quiet."),
    "logged": Capability("every hour logged", "B6", "Every hour has a decision and a reason, including silences."),
}

LAYER_LABELS = {
    "S1": "Fetch", "S2": "Data", "S2/U2": "Data", "S3": "Place", "U1": "Normal", "U2": "Scores",
    "D1": "Trigger", "D2": "Story", "D3": "Worth it", "D4": "Pace", "D5": "Arbitrate",
    "D6": "Respond", "D7": "Budget", "D8": "Timing", "A": "Compose", "A1": "Compose", "A2": "Deliver",
}

# What the agent did, said the way a person would. {name} is the user, {at} the decision's local time.
SENTENCES = {
    "SENT_OPENED": "Sent a message: the air turned bad in a way worth knowing about.",
    "SENT_ESCALATED": "Sent an update: the air got a full band worse since the last message.",
    "SENT_CLEARED": "Sent an all-clear: a genuinely bad spell is over.",
    "SENT_CHECK_IN": "Spoke at {name}'s check-in, the time {name} chose to hear from it.",
    "SENT_SEVERE_BYPASS": "Sent a message at once: very unhealthy air breaks through quiet hours.",
    "QUIET_HOURS_HELD": "Held a message: worth telling {name}, but it's quiet hours. It goes out in the morning.",
    "HELD_RELEASED": "Quiet hours ended, so everything held went out as one message.",
    "HELD_EXPIRED": "Dropped the held message: the spell ended before morning, so there was nothing left to say.",
    "CHECKIN_QUIET": "Ran {name}'s check-in and found nothing worse than usual, so stayed quiet.",
    "DEDUP_SAME_BAND": "Stayed quiet: same story, same band as the last message.",
    "EPISODE_CONTINUES": "Stayed quiet: the same bad spell is still going, with nothing new to say.",
    "COOLDOWN": "Stayed quiet: too soon after the last message in this story.",
    "DAILY_BUDGET": "Stayed quiet: {name} has had enough messages for today.",
    "ARBITRATED_OUT": "Stayed quiet: a more important message won this hour.",
    "BELOW_RELEVANCE": "Stayed quiet: unusual for here, but the air is still good.",
    "RECOVERY_NOT_WORTH_SAYING": "Stayed quiet: the spell ended, but it was too short and mild to need an all-clear.",
    "NO_TRIGGER": "Stayed quiet: nothing unusual for this hour.",
    "NO_DATA": "Couldn't judge: no new readings from the sensor.",
    "NO_DATA_TIMEOUT": "Closed the story quietly after a day without data, rather than guess.",
    "NO_BASELINE": "Still learning what's normal for this place.",
    "DQ_SUSPECT": "Stayed quiet: a reading was ignored as a one-hour sensor glitch.",
    "DQ_INVALID": "Stayed quiet: an impossible reading was ignored.",
    "DQ_STUCK": "Stayed quiet: the sensor was stuck on one value, so those hours were ignored.",
    "DQ_LOW_COVERAGE": "Stayed quiet: the hour had too little data to trust.",
    "RULES_INVALID": "Used the previous settings: the new ones didn't validate.",
}


def sentence(d: Decision, name: str) -> str:
    template = SENTENCES.get(d.reason_code)
    return template.format(name=name) if template else (d.reason or d.reason_code)


def _detail(t: TraceEntry) -> str:
    """A few words from a layer's values, enough to read the path at a glance."""
    v = t.values or {}
    if t.layer == "D1":
        fired = v.get("fired") or v.get("kinds")
        if isinstance(fired, list) and fired:
            return ", ".join(map(str, fired))
        return v.get("event_kind") or ""
    if t.layer == "D2":
        return str(v.get("transition") or v.get("candidate") or v.get("state") or "").lower()
    if t.layer == "D8":
        if v.get("check_in_wins"):
            return "check-in wins"
        if v.get("quiet_hours") is True or v.get("in_quiet_hours"):
            return "quiet hours"
    return ""


def layer_path(d: Decision) -> list[dict]:
    """One chip per trace entry: label, pass/fail, a short detail. The first failure is where it stopped."""
    chips, stopped = [], False
    for t in d.trace:
        failed = not t.passed
        chips.append({
            "label": LAYER_LABELS.get(t.layer, t.layer),
            "layer": t.layer,
            "passed": t.passed,
            "detail": _detail(t),
            "stop": failed and not stopped,
            "code": t.reason_code,
        })
        stopped = stopped or failed
    return chips
