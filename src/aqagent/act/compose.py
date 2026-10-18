"""A1 COMPOSE, part 2: write the notice from the insight (S-C §9).

An LLM writes one or two sentences; a validator checks them; a template writes the message from the same facts
whenever the LLM is missing, slow, failing or invalid. The LLM call runs in a daemon thread with a timeout, so a
hanging provider can't stall the hourly run.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from aqagent import params
from aqagent.act.facts import part_of_day
from aqagent.types import Band

log = logging.getLogger(__name__)

LLM = Callable[[str], str]


@dataclass(frozen=True)
class ComposedMessage:
    body: str
    next_action: str
    generator: str  # "llm" | "template"


# ---------------------------------------------------------------- validator

_BARE_AQI = re.compile(r"^\s*AQI is now \d+\.?\s*$", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_WORD = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_WORDS = re.compile(
    rf"\b\d{{1,2}}\s+{_MONTH_WORD}\b|\b{_MONTH_WORD}\s+\d{{1,2}}\b"
    r"|\b(?:january|february|march|april|june|july|august|september|october|november|december)\b"
    r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def _norm_number(token: str) -> str:
    return str(float(token)) if "." in token else str(int(token))


def _actions_in(body: str, candidates: list[str]) -> list[str]:
    low = body.lower()
    return [a for a in candidates if a.lower() in low]


def validate_message(body: str, insight: dict) -> list[str]:
    """Errors (empty = valid): length, not JSON, not a bare status, exactly one action, no invented numbers/dates."""
    errors: list[str] = []
    text = (body or "").strip()
    if not text:
        return ["empty body"]
    if len(text) > params.MESSAGE_MAX_CHARS:
        errors.append(f"length {len(text)} > {params.MESSAGE_MAX_CHARS}")
    if text[0] in "{[":
        errors.append("looks like JSON")
    if _BARE_AQI.match(text):
        errors.append("bare 'AQI is now N' status")
    found = _actions_in(text, insight.get("action_candidates") or [])
    if len(found) != 1:
        errors.append(f"expected exactly one action from action_candidates, found {len(found)}")

    dump = json.dumps(insight, ensure_ascii=False).lower()
    known_numbers = {_norm_number(t) for t in _NUMBER.findall(dump)}
    for token in _NUMBER.findall(text):
        if _norm_number(token) not in known_numbers:
            errors.append(f"number {token!r} is not in the insight")
    for m in _DATE_WORDS.finditer(text):
        for word in re.findall(r"[a-z]+", m.group(0).lower()):
            stem = word[:3] if word[:3] in _MONTHS else word
            if stem not in dump:
                errors.append(f"date word {word!r} is not in the insight")
    return errors


# ---------------------------------------------------------------- template


def _label(slug: str | None) -> str | None:
    return Band.parse(slug).label if slug else None


def _clause(fact: str | None) -> str:
    if not fact:
        return ""
    if fact.startswith("since "):
        return f" {fact}"
    if fact.startswith("worst ") or fact.split(" ", 1)[0] in (
        "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"
    ):
        return f", the {fact}"
    return f", {fact}"


def _part_of_day(insight: dict) -> str:
    return part_of_day(datetime.fromisoformat(insight["local_time"]))[0]


def _lead(insight: dict, with_extra: bool) -> str:
    who = f"{insight['city']}'s air" if insight.get("city") else "The air"
    now_band = insight["now"]["band"]
    label = _label(now_band)
    facts = insight.get("history_facts") or []
    since = next((f for f in facts if f.startswith("since ")), None)
    back = next((f for f in facts if f.startswith("back to ")), None)
    other = next((f for f in facts if f not in (since, back)), None)
    extra = other if with_extra else None
    episode = insight.get("episode") or {}
    kind = insight["kind"]
    event = insight.get("event_kind")

    if kind == "cleared":
        return f"{who} is {back}" if back else f"{who} is back to its usual level"

    if kind == "released_after_quiet_hours":
        peak = episode.get("peak") or {}
        peak_label = _label(peak.get("band")) or label
        at = f" around {peak['at']}" if peak.get("at") else ""
        state = f"it's still {label}" if peak_label == label else f"it's {label} now"
        return f"Overnight, {who.replace('The air', 'the air')} reached {peak_label}{at}, and {state}"

    if kind == "check_in":
        typical = (insight.get("typical_for_this_hour") or {}).get("band")
        lead = f"{who} has been {label} {since}" if since else f"{who} is {label}"
        if typical and Band.parse(now_band) > Band.parse(typical):
            if not any("usual" in f for f in facts):
                lead += f", worse than a usual {_part_of_day(insight)} here"
        elif typical:
            lead += ", about usual for this time of day"
        return lead + _clause(extra)

    if event == "spike":
        if extra:
            return f"{who} jumped sharply to {label}{_clause(extra)}"
        return f"{who} jumped sharply to {label}{_clause(since)}"
    if event == "climb":
        return f"{who} has been getting worse{_clause(since)} and is now {label}{_clause(extra)}"
    if event == "elevated":
        hours = episode.get("hours")
        span = f"for {hours} hour{'s' if hours != 1 else ''}" if hours else "for a while"
        since_part = f", {since}," if since else ""
        return f"{who} has been stuck above normal {span}{since_part} and is now {label}{_clause(extra)}"
    if event == "floor":
        return f"{who} has crossed into {label}{_clause(extra or since)}"
    return f"{who} got worse and is now {label}{_clause(extra or since)}"


def _action_sentence(insight: dict, action: str) -> str:
    fresh = insight["kind"] == "cleared" or insight["now"]["band"] == Band.GOOD.slug
    return f"Good time to {action}." if fresh else f"Best to {action} for now."


def template(insight: dict) -> ComposedMessage:
    """Deterministic message from the same facts: one past-context fact, exactly one action."""
    action = (insight.get("action_candidates") or ["keep an eye on the air"])[0]
    body = ""
    for with_extra in (True, False):
        body = f"{_lead(insight, with_extra)}. {_action_sentence(insight, action)}"
        if len(body) <= params.MESSAGE_MAX_CHARS:
            break
    return ComposedMessage(body, action, "template")


# ---------------------------------------------------------------- LLM

_WORDING = {
    "spike": "it jumped sharply",
    "climb": "it has been getting worse since the episode started",
    "elevated": "it has been stuck above normal for a while",
    "floor": "it has crossed into a worse band",
}


def build_prompt(insight: dict) -> str:
    hint = _WORDING.get(insight.get("event_kind") or "", "")
    if insight["kind"] == "cleared":
        hint = "it is back to its usual level"
    elif insight["kind"] == "released_after_quiet_hours":
        hint = "what happened overnight, then how it is now"
    return (
        "Write a short phone notification about local air quality for the person in the JSON below.\n"
        "Rules:\n"
        f"- One or two sentences of plain text, at most {params.MESSAGE_MAX_CHARS} characters in total.\n"
        "- Use only the facts in the JSON. Do not mention any number, time or date that isn't in it.\n"
        "- Include at least one item from history_facts, so the reader gets past context.\n"
        "- Include exactly one phrase from action_candidates, word for word, and no other advice.\n"
        "- Don't write a bare status like 'AQI is now 142'. Describe the band in words.\n"
        + (f"- Convey that {hint}.\n" if hint else "")
        + "- Return only the notification text: no JSON, no quotes, no preamble.\n\n"
        f"JSON:\n{json.dumps(insight, ensure_ascii=False)}\n"
    )


def _call_with_timeout(llm: LLM, prompt: str, timeout_s: float) -> str:
    future: Future = Future()

    def run() -> None:
        try:
            future.set_result(llm(prompt))
        except BaseException as exc:  # surfaced through the future
            future.set_exception(exc)

    threading.Thread(target=run, name="aqagent-llm", daemon=True).start()
    return future.result(timeout=timeout_s)


def _clean(text: str) -> str:
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def compose(insight: dict, llm: LLM | None, timeout_s: float = params.LLM_TIMEOUT_S) -> ComposedMessage:
    """LLM first (validated), template otherwise. Never raises because of the LLM."""
    if llm is None:
        return template(insight)
    try:
        body = _clean(_call_with_timeout(llm, build_prompt(insight), timeout_s))
    except FutureTimeout:
        log.warning("A1 compose: LLM timed out after %ss; falling back to template", timeout_s)
        return template(insight)
    except Exception as exc:
        log.warning("A1 compose: LLM failed (%s); falling back to template", exc)
        return template(insight)
    errors = validate_message(body, insight)
    if errors:
        log.warning("A1 compose: LLM output rejected (%s); falling back to template", "; ".join(errors))
        return template(insight)
    action = _actions_in(body, insight["action_candidates"])[0]
    return ComposedMessage(body, action, "llm")


def anthropic_llm(model: str | None = None) -> LLM | None:
    """A prompt -> text callable on the Anthropic Messages API, or None without ANTHROPIC_API_KEY / the SDK."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("A1 compose: ANTHROPIC_API_KEY is set but the 'anthropic' package isn't installed")
        return None
    model = model or os.environ.get("AQAGENT_LLM_MODEL") or params.DEFAULT_LLM_MODEL
    # The compose thread enforces the overall deadline; no SDK retries, so a timed-out call doesn't linger.
    client = anthropic.Anthropic(timeout=params.LLM_TIMEOUT_S, max_retries=0)

    def call(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("LLM refused")
        return "".join(b.text for b in response.content if b.type == "text")

    return call
