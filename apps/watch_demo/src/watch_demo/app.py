"""The watch demo: a server-rendered watch face, letterboxed, beside a chart of the data behind it.

Everything inside the watch is the product. Everything around it is the demo frame: the
scenario navigator, the story card with its beats, the chart, and the "at this moment" panel
that says in plain English what the agent decided and why. Every beat and every hour on the
chart is a link that moves the watch to that moment (`?t=<ISO UTC>`). No JavaScript.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .capabilities import CAPABILITIES, layer_path, sentence
from .chart import OUTCOME_LABELS, build_chart
from .client import AgentClient, client_from_env
from .models import Decision, Reading
from .scenarios import GROUPS, Scenario, load_scenarios
from .why import BAND_LABELS, clock, relative, silence_line, user_tz, why_lines

HERE = Path(__file__).parent
SILENCE_WINDOW = timedelta(hours=12)
HOUR = timedelta(hours=1)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _groups(scenarios: list[Scenario]) -> list[dict]:
    """The navigator: scenarios under their group headings, in a fixed order."""
    out = []
    for key, title in [*GROUPS.items(), (None, "Scenarios")]:
        items = [s for s in scenarios if (s.group if s.group in GROUPS else None) == key]
        if items:
            out.append({"title": title, "items": items})
    return out


def create_app(client: AgentClient | None = None, scenarios: list[Scenario] | None = None) -> FastAPI:
    client = client or client_from_env()
    scenarios = scenarios or load_scenarios()
    by_id = {s.id: s for s in scenarios}
    groups = _groups(scenarios)

    app = FastAPI(title="Air quality agent: watch demo", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    def pick(scenario_id: str | None) -> Scenario:
        if scenario_id is None:
            return scenarios[0]
        if scenario_id not in by_id:
            raise HTTPException(404, f"unknown scenario {scenario_id!r}")
        return by_id[scenario_id]

    def moment(sc: Scenario, t: str | None) -> datetime:
        """The replayed 'now' for the watch: `t` if given (clamped to the window), else the first beat."""
        if not t:
            return sc.opens_at
        try:
            when = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"bad time {t!r}; use ISO 8601 UTC")
        return min(max(when, sc.start), sc.until)

    def find_user(user_id: str):
        user = next((u for u in client.users() if u.id == user_id), None)
        if user is None:
            raise HTTPException(404, f"unknown user {user_id!r}")
        return user

    def query(sc: Scenario, now: datetime) -> str:
        params = {"scenario": sc.id}
        if now != sc.opens_at:
            params["t"] = _iso(now)
        return urlencode(params)

    def href(sc: Scenario, now: datetime) -> str:
        return f"/?{query(sc, now)}"

    def story(sc: Scenario, now: datetime) -> dict:
        """The story card: tags, beats (with the current one marked), and prev/next links."""
        beats = [{"n": i + 1, "beat": b, "href": href(sc, b.at)} for i, b in enumerate(sc.beats)]
        current = max((b["n"] for b in beats if b["beat"].at <= now), default=0)
        for b in beats:
            b["current"] = b["n"] == current
        prev_beat = next((b for b in reversed(beats) if b["beat"].at < now), None)
        next_beat = next((b for b in beats if b["beat"].at > now), None)
        return {
            "tags": [CAPABILITIES[k] for k in sc.shows if k in CAPABILITIES],
            "beats": beats,
            "prev_beat": prev_beat,
            "next_beat": next_beat,
            "prev_hour": href(sc, max(now - HOUR, sc.start)) if now > sc.start else None,
            "next_hour": href(sc, min(now + HOUR, sc.until)) if now < sc.until else None,
        }

    def frame(sc: Scenario, user, now: datetime, focus: datetime | None = None) -> dict:
        """The demo side: chart plus what the agent decided at the selected moment (or the focused notice)."""
        tz = user_tz(user)
        readings = client.readings(user.station_id, sc.start, sc.until)
        decisions = client.decisions(sc.user_id, sc.start, sc.until, replay_run=sc.replay_run)
        chart = build_chart(
            readings, decisions, sc.start, sc.until, now, tz,
            href=lambda t: href(sc, t), city=user.city, focus=focus,
            beats=[(i + 1, b.at) for i, b in enumerate(sc.beats)],
        )
        decided = _latest(decisions, focus or now)
        reading = _reading_at(readings, decided.about if decided else (focus or now))
        lag = decided and decided.period_end and decided.evaluated_at - decided.period_end >= timedelta(minutes=10)
        return {
            "chart": chart,
            "decided": decided,
            "decided_at": clock(decided.evaluated_at, tz) if decided else None,
            "decided_about": clock(decided.period_end, tz) if lag else None,
            "decided_label": OUTCOME_LABELS[decided.outcome] if decided else None,
            "decided_sentence": sentence(decided, user.display_name) if decided else None,
            "path": layer_path(decided) if decided else [],
            "reading": reading,
            "reading_at": clock(reading.at, tz) if reading else None,
            "last_reading": max((r.at for r in readings if r.at <= now), default=None),
        }

    def page(request: Request, sc: Scenario, now: datetime, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "watch.html",
            {
                "scenarios": scenarios, "groups": groups, "scenario": sc, "band_labels": BAND_LABELS,
                "story": story(sc, now), "q": query(sc, now), **ctx,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def watch(request: Request, scenario: str | None = None, t: str | None = None):
        sc = pick(scenario)
        now = moment(sc, t)
        try:
            user = find_user(sc.user_id)
            feed = client.feed(sc.user_id, sc.replay_run, now)
            if sc.limit:
                feed = feed[: sc.limit]
            side = frame(sc, user, now)
            silence, face = None, "clear"
            if not feed:
                recent = client.decisions(sc.user_id, now - SILENCE_WINDOW, now, replay_run=sc.replay_run)
                silence = silence_line(recent, user)
                latest = _latest(recent, now)
                if latest and latest.reason_code in ("NO_DATA", "NO_DATA_TIMEOUT"):
                    face = "no-data"
                    last = side["last_reading"]
                    silence = f"Nothing from the {user.city} sensor since {clock(last, user_tz(user))}" if last else None
                elif any(d.reason_code == "QUIET_HOURS_HELD" for d in recent):
                    face = "holding"
        except httpx.HTTPError as exc:
            return page(request, sc, now, view="error", error=str(exc), now_local=None)
        cards = [{"n": n, "ago": relative(n.shown_at, now)} for n in feed]
        return page(
            request,
            sc,
            now,
            view="feed" if cards else "empty",
            user=user,
            cards=cards,
            silence=silence,
            face=face,
            now_local=now.astimezone(user_tz(user)),
            **side,
        )

    @app.get("/why/{notification_id}", response_class=HTMLResponse)
    def why(request: Request, notification_id: str, scenario: str | None = None, t: str | None = None):
        sc = pick(scenario)
        now = moment(sc, t)
        user = find_user(sc.user_id)
        feed = client.feed(sc.user_id, sc.replay_run, now)
        n = next((x for x in feed if x.id == notification_id), None)
        if n is None:
            raise HTTPException(404, f"notification {notification_id!r} not in this scenario")
        try:
            ex = client.explain(notification_id)
        except (KeyError, httpx.HTTPError):
            raise HTTPException(404, f"no explanation for {notification_id!r}")
        side = frame(sc, user, now, focus=ex.decision.evaluated_at)
        return page(
            request,
            sc,
            now,
            view="why",
            user=user,
            n=n,
            ago=relative(n.shown_at, now),
            lines=why_lines(n, ex, user),
            decision=ex.decision,
            now_local=now.astimezone(user_tz(user)),
            **side,
        )

    @app.get("/capabilities", response_class=HTMLResponse)
    def capabilities(request: Request):
        """Every capability, the brief requirement it answers, and the scenarios (and beat) that show it."""
        rows = []
        for key, cap in sorted(CAPABILITIES.items(), key=lambda kv: (kv[1].brief, kv[1].label)):
            shown = [s for s in scenarios if key in s.shows]
            rows.append({"key": key, "cap": cap, "scenarios": shown})
        return templates.TemplateResponse(request, "capabilities.html", {"rows": rows, "groups": groups})

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def _latest(decisions: list[Decision], now: datetime) -> Decision | None:
    """The decision in force at `now`; a message or a hold outranks a routine hour at the same time."""
    past = [d for d in decisions if d.evaluated_at <= now]
    if not past:
        return None
    rank = {"no_event": 0, "suppressed": 1, "held": 2, "sent": 3}
    return max(past, key=lambda d: (d.evaluated_at, rank[d.outcome]))


def _reading_at(readings: list[Reading], when: datetime) -> Reading | None:
    past = [r for r in readings if r.at <= when]
    return past[-1] if past else None
