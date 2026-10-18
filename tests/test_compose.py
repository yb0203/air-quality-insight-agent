"""A1 COMPOSE: insight builder, history facts, template, validator and LLM fallback (QA-MSG-*)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from aqagent import params
from aqagent.act import compose as compose_mod
from aqagent.act.compose import ComposedMessage, anthropic_llm, compose, template, validate_message
from aqagent.act.facts import ACTION_CATALOGUE, build_insight, history_facts
from aqagent.types import Band, Candidate, CandidateKind, EventKind, StationScore
from aqagent.understand.aqi import aqi_value, band_for

UTC = timezone.utc
DELHI = ZoneInfo("Asia/Kolkata")
AT = datetime(2026, 10, 18, 2, 30, tzinfo=UTC)  # 08:00 in Delhi
ARJUN = {"name": "Arjun", "persona": {"habits": ["morning run 06:30"], "conditions": []}}
MEERA = {"name": "Meera", "persona": {"habits": [], "conditions": []}}
BARE_AQI = re.compile(r"^\s*AQI is now \d+\.?\s*$", re.IGNORECASE)


def score(t: datetime, nowcast: float | None, typical: Band = Band.USG, slope: float = 0.0) -> StationScore:
    band = band_for(nowcast) if nowcast is not None else None
    return StationScore(1, t, 1.0, 1.0, 0.0, slope, nowcast, band, typical)


def delhi_week(current: float = 142.0) -> list[StationScore]:
    """Seven days of ordinary Delhi (45, USG = typical), a 160 hour on 13 Oct, bad mornings on 16 and 17 Oct,
    and a bad spell from 02:00 local today peaking at 151 at 06:00, now `current` at 08:00."""
    out = []
    start = AT - timedelta(days=7)
    t = start
    while t <= AT:
        local = t.astimezone(DELHI)
        v = 45.0
        if local.date().isoformat() == "2026-10-13" and local.hour == 20:
            v = 160.0
        if local.date().isoformat() in ("2026-10-16", "2026-10-17") and local.hour == 8:
            v = 80.0
        if local.date().isoformat() == "2026-10-18" and local.hour >= 2:
            v = {6: 151.0}.get(local.hour, 120.0)
        if t == AT:
            v = current
        out.append(score(t, v, slope=0.05))
        t += timedelta(hours=1)
    return out


EPISODE = {
    "opened_at": datetime(2026, 10, 17, 20, 30, tzinfo=UTC),  # 02:00 local
    "peak_value": 151.0,
    "peak_band": "very_unhealthy",
    "peak_at": datetime(2026, 10, 18, 0, 30, tzinfo=UTC),  # 06:00 local
    "hours": 6,
}


# ---------------------------------------------------------------- history facts


def test_history_fact_worst_since_date():
    facts = history_facts(delhi_week(), AT, DELHI, EPISODE)
    assert "worst since 13 Oct" in facts


def test_history_fact_nth_bad_morning_this_week():
    facts = history_facts(delhi_week(), AT, DELHI, EPISODE)
    assert "third bad morning this week" in facts


def test_history_fact_since_local_hour():
    facts = history_facts(delhi_week(), AT, DELHI, EPISODE)
    assert "since 2am" in facts


def test_history_fact_back_to_normal_after_hours():
    calm = [score(AT - timedelta(hours=i), 40.0) for i in range(5, -1, -1)]
    episode = dict(EPISODE, hours=16)
    facts = history_facts(calm, AT, DELHI, episode, kind=CandidateKind.cleared)
    assert "back to its usual level after 16 hours" in facts
    assert not any(f.startswith("since") for f in facts)


def test_history_facts_are_deterministic_and_quiet_without_history():
    assert history_facts(delhi_week(), AT, DELHI, EPISODE) == history_facts(delhi_week(), AT, DELHI, EPISODE)
    assert history_facts([], AT, DELHI, None) == []


# ---------------------------------------------------------------- insight


def insight_for(kind: CandidateKind, event_kind: EventKind | None = EventKind.climb, *, user=ARJUN,
                at: datetime = AT, history=None, episode=EPISODE, absorbed=()):
    history = delhi_week() if history is None else history
    now = [s for s in history if s.period_end == at][-1]
    band = now.band
    return build_insight(
        Candidate(kind, band, episode_id=7, event_kind=event_kind, severe=band.is_severe),
        user=user, city="Delhi", tz=DELHI, at=at, score=now, typical_pm25=48.0,
        episode=episode, history=history, absorbed_held=list(absorbed),
    )


def test_build_insight_shape():
    ins = insight_for(CandidateKind.escalated)
    assert ins["kind"] == "escalated"
    assert ins["event_kind"] == "climb"
    assert ins["city"] == "Delhi"
    assert ins["local_time"] == "2026-10-18T08:00+05:30"
    assert ins["now"] == {"pm25": 142, "band": "very_unhealthy", "aqi": aqi_value(142.0)}
    assert ins["typical_for_this_hour"] == {"pm25": 48, "band": "usg"}
    assert ins["episode"] == {"started": "since 2am", "hours": 6, "peak": {"pm25": 151, "band": "very_unhealthy", "at": "6am"}}
    assert ins["history_facts"][:1] and "worst since 13 Oct" in ins["history_facts"]
    assert ins["trend"]["direction"] == "rising"
    assert ins["user"] == ARJUN
    assert ins["action_candidates"] and all(isinstance(a, str) for a in ins["action_candidates"])
    json.dumps(ins)  # plain JSON


def test_released_kind_name_and_absorbed():
    held = [Candidate(CandidateKind.opened, Band.UNHEALTHY, 7, EventKind.climb)]
    ins = insight_for(CandidateKind.released, absorbed=held)
    assert ins["kind"] == "released_after_quiet_hours"
    assert ins["absorbed_held"] == [{"kind": "opened", "band": "unhealthy", "event_kind": "climb"}]


def test_action_catalogue_covers_every_kind_and_band():
    for kind in CandidateKind:
        for band in Band:
            actions = ACTION_CATALOGUE[(kind, band)]
            assert actions, (kind, band)
            # no action is a substring of another, so "exactly one" is countable
            for a in actions:
                assert not any(a != b and a in b for b in actions), (kind, band, a)


# ---------------------------------------------------------------- template and validator


def every_kind_insights() -> list[dict]:
    held = [Candidate(CandidateKind.opened, Band.UNHEALTHY, 7, EventKind.climb)]
    calm = delhi_week(current=40.0)
    out = [insight_for(CandidateKind.opened, ek) for ek in EventKind]
    out += [insight_for(CandidateKind.escalated, ek) for ek in (*EventKind, None)]
    out.append(insight_for(CandidateKind.cleared, None, history=calm, episode=dict(EPISODE, hours=16)))
    out.append(insight_for(CandidateKind.check_in, None, absorbed=held))
    out.append(insight_for(CandidateKind.released, EventKind.climb, absorbed=held))
    out.append(insight_for(CandidateKind.opened, EventKind.spike, user=MEERA, episode=None))
    return out


def test_qa_msg_01_shape():
    for ins in every_kind_insights():
        msg = template(ins)
        assert isinstance(msg, ComposedMessage) and msg.generator == "template"
        assert 0 < len(msg.body) <= params.MESSAGE_MAX_CHARS, msg.body
        with pytest.raises(ValueError):
            json.loads(msg.body)
        assert not BARE_AQI.match(msg.body)
        assert validate_message(msg.body, ins) == [], (ins["kind"], ins["event_kind"], msg.body)


def test_qa_msg_02_one_action():
    for ins in every_kind_insights():
        msg = template(ins)
        present = [a for a in ins["action_candidates"] if a.lower() in msg.body.lower()]
        assert present == [msg.next_action], msg.body


def test_qa_msg_03_past_context():
    cases = [insight_for(CandidateKind.opened, ek) for ek in (EventKind.spike, EventKind.climb, EventKind.elevated)]
    cases.append(insight_for(CandidateKind.cleared, None, history=delhi_week(current=40.0),
                             episode=dict(EPISODE, hours=16)))
    for ins in cases:
        assert ins["history_facts"], ins["kind"]
        body = template(ins).body.lower()
        assert any(f.lower() in body for f in ins["history_facts"]), body


def test_event_kind_wording():
    wording = {EventKind.spike: "jumped sharply", EventKind.climb: "getting worse since",
               EventKind.elevated: "stuck above normal for", EventKind.floor: "has crossed into"}
    for ek, phrase in wording.items():
        assert phrase in template(insight_for(CandidateKind.opened, ek)).body
    cleared = insight_for(CandidateKind.cleared, None, history=delhi_week(current=40.0), episode=dict(EPISODE, hours=16))
    assert "back to its usual level after 16 hours" in template(cleared).body


def test_validator_rejects_bare_status_and_json_and_two_actions():
    ins = insight_for(CandidateKind.opened, EventKind.climb)
    assert validate_message("AQI is now 217", ins)
    assert validate_message(json.dumps({"msg": ins["action_candidates"][0]}), ins)
    two = f"Air is bad since 2am. {ins['action_candidates'][0]} and {ins['action_candidates'][1]}."
    assert any("action" in e for e in validate_message(two, ins))
    assert any("length" in e for e in validate_message("x" * 400 + ins["action_candidates"][0], ins))


def test_validator_rejects_unknown_dates():
    ins = insight_for(CandidateKind.opened, EventKind.climb)
    body = f"Delhi's air is the worst since 3 March. Best to {ins['action_candidates'][0]}."
    errors = validate_message(body, ins)
    assert any("3" in e for e in errors) and any("march" in e.lower() for e in errors)


# ---------------------------------------------------------------- compose with an LLM


def test_qa_msg_04_no_invented_numbers():
    ins = insight_for(CandidateKind.opened, EventKind.climb)
    errors = validate_message("AQI hit 999", ins)
    assert any("999" in e for e in errors)
    msg = compose(ins, lambda prompt: "AQI hit 999")
    assert msg.generator == "template"
    assert validate_message(msg.body, ins) == []


def test_qa_msg_05_no_llm():
    ins = insight_for(CandidateKind.opened, EventKind.spike)
    msg = compose(ins, None)
    assert msg.generator == "template"
    assert validate_message(msg.body, ins) == []


def test_qa_msg_06_bad_llm_output(caplog):
    ins = insight_for(CandidateKind.opened, EventKind.climb)
    action = ins["action_candidates"][0]
    too_long = ("Delhi's air has been getting worse since 2am " * 10)[:390] + action
    for bad in (too_long, "Delhi's air has been getting worse since 2am. Take care."):
        with caplog.at_level("WARNING"):
            msg = compose(ins, lambda prompt, b=bad: b)
        assert msg.generator == "template"
        assert validate_message(msg.body, ins) == []
    assert "falling back to template" in caplog.text


def test_llm_output_that_validates_is_used():
    ins = insight_for(CandidateKind.opened, EventKind.climb)
    prompts = []
    good = "Delhi's air has been getting worse since 2am, the worst since 13 Oct. Best to stay indoors with windows closed."

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return f'  "{good}"\n'

    msg = compose(ins, llm)
    assert msg == ComposedMessage(good, "stay indoors with windows closed", "llm")
    prompt = prompts[0]
    assert "action_candidates" in prompt and "one or two sentences" in prompt.lower()
    assert json.dumps(ins["history_facts"]) in prompt


def test_llm_exception_falls_back():
    def boom(prompt):
        raise RuntimeError("overloaded")

    assert compose(insight_for(CandidateKind.opened, EventKind.climb), boom).generator == "template"


def test_review_llm_timeout_falls_back():
    ins = insight_for(CandidateKind.opened, EventKind.climb)

    def hanging(prompt):
        time.sleep(30)
        return "never"

    t0 = time.monotonic()
    msg = compose(ins, hanging, timeout_s=0.2)
    assert time.monotonic() - t0 < 1.0
    assert msg.generator == "template"
    assert validate_message(msg.body, ins) == []


# ---------------------------------------------------------------- persona and released


def test_qa_msg_07_persona_action():
    six_am = datetime(2026, 10, 18, 0, 30, tzinfo=UTC)  # 06:00 Delhi
    history = [s for s in delhi_week() if s.period_end <= six_am]
    ins = insight_for(CandidateKind.opened, EventKind.climb, at=six_am, history=history)
    msg = template(ins)
    assert "run" in msg.next_action and msg.next_action in msg.body
    other = insight_for(CandidateKind.opened, EventKind.climb, user=MEERA, at=six_am, history=history)
    assert not any("run" in a for a in other["action_candidates"])
    # after the run's hour, the run action is no longer offered for bad air
    late = insight_for(CandidateKind.opened, EventKind.climb)  # 08:00, run was 06:30
    assert not any("run" in a for a in late["action_candidates"])


def test_qa_msg_08_released_mentions_night():
    held = [Candidate(CandidateKind.opened, Band.UNHEALTHY, 7, EventKind.climb),
            Candidate(CandidateKind.escalated, Band.VERY_UNHEALTHY, 7, EventKind.floor)]
    ins = insight_for(CandidateKind.released, EventKind.climb, absorbed=held)
    body = template(ins).body
    assert "overnight" in body.lower()
    assert "6am" in body  # the peak time
    assert Band.VERY_UNHEALTHY.label in body  # the current state
    assert validate_message(body, ins) == []


# ---------------------------------------------------------------- the Anthropic adapter (never calls the API)


def test_anthropic_llm_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert anthropic_llm() is None


def test_anthropic_llm_uses_env_model_and_returns_text(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            block = type("B", (), {"type": "text", "text": "Hello there."})()
            return type("R", (), {"content": [block], "stop_reason": "end_turn"})()

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AQAGENT_LLM_MODEL", "claude-test-model")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    llm = anthropic_llm()
    assert llm is not None
    assert llm("the prompt") == "Hello there."
    assert calls["model"] == "claude-test-model"
    assert calls["messages"] == [{"role": "user", "content": "the prompt"}]

    monkeypatch.delenv("AQAGENT_LLM_MODEL")
    anthropic_llm()("p")
    assert calls["model"] == params.DEFAULT_LLM_MODEL
    anthropic_llm("claude-explicit")("p")
    assert calls["model"] == "claude-explicit"
