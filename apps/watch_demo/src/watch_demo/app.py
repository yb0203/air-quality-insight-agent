"""The watch demo: a server-rendered watch face, letterboxed, beside a chart of the data behind it.

Everything inside the watch is the product. The chart, the scenario chips and the
decision line are the demo frame: they show what the agent saw and decided, hour by
hour, and clicking any hour moves the watch to that moment (`?t=<ISO UTC>`).
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

from .chart import OUTCOME_LABELS, build_chart
from .client import AgentClient, client_from_env
from .models import Decision, Reading
from .scenarios import Scenario, load_scenarios
from .why import BAND_LABELS, clock, relative, silence_line, user_tz, why_lines

HERE = Path(__file__).parent
SILENCE_WINDOW = timedelta(hours=12)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def create_app(client: AgentClient | None = None, scenarios: list[Scenario] | None = None) -> FastAPI:
    client = client or client_from_env()
    scenarios = scenarios or load_scenarios()
    by_id = {s.id: s for s in scenarios}

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
        """The replayed 'now' for the watch: `t` if given, clamped to the chart window."""
        if not t:
            return sc.until
        try:
            when = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"bad time {t!r}; use ISO 8601 UTC")
        start = sc.until - timedelta(hours=sc.chart_hours)
        return min(max(when, start), sc.until)

    def find_user(user_id: str):
        user = next((u for u in client.users() if u.id == user_id), None)
        if user is None:
            raise HTTPException(404, f"unknown user {user_id!r}")
        return user

    def query(sc: Scenario, now: datetime) -> str:
        params = {"scenario": sc.id}
        if now != sc.until:
            params["t"] = _iso(now)
        return urlencode(params)

    def frame(sc: Scenario, user, now: datetime, focus: datetime | None = None) -> dict:
        """The demo side: chart plus what the agent decided at the selected moment (or the focused notice)."""
        start = sc.until - timedelta(hours=sc.chart_hours)
        tz = user_tz(user)
        readings = client.readings(user.station_id, start, sc.until)
        decisions = client.decisions(sc.user_id, start, sc.until, replay_run=sc.replay_run)
        chart = build_chart(
            readings, decisions, start, sc.until, now, tz,
            href=lambda t: f"/?{query(sc, t)}", city=user.city, focus=focus,
        )
        decided = _latest(decisions, focus or now)
        reading = _latest_reading(readings, focus or now)
        return {
            "chart": chart,
            "decided": decided,
            "decided_at": clock(decided.evaluated_at, tz) if decided else None,
            "decided_label": OUTCOME_LABELS[decided.outcome] if decided else None,
            "reading": reading,
            "reading_at": clock(reading.at, tz) if reading else None,
        }

    def page(request: Request, sc: Scenario, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "watch.html",
            {"scenarios": scenarios, "scenario": sc, "band_labels": BAND_LABELS, **ctx},
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
            silence, holding = None, False
            if not feed:
                recent = client.decisions(sc.user_id, now - SILENCE_WINDOW, now, replay_run=sc.replay_run)
                silence = silence_line(recent, user)
                holding = any(d.reason_code == "QUIET_HOURS_HELD" for d in recent)
            side = frame(sc, user, now)
        except httpx.HTTPError as exc:
            return page(request, sc, view="error", error=str(exc), now_local=None, q=query(sc, now))
        cards = [{"n": n, "ago": relative(n.shown_at, now)} for n in feed]
        return page(
            request,
            sc,
            view="feed" if cards else "empty",
            user=user,
            cards=cards,
            silence=silence,
            holding=holding,
            now_local=now.astimezone(user_tz(user)),
            q=query(sc, now),
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
            view="why",
            user=user,
            n=n,
            ago=relative(n.shown_at, now),
            lines=why_lines(n, ex, user),
            decision=ex.decision,
            now_local=now.astimezone(user_tz(user)),
            q=query(sc, now),
            **side,
        )

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


def _latest_reading(readings: list[Reading], now: datetime) -> Reading | None:
    past = [r for r in readings if r.at <= now]
    return past[-1] if past else None
