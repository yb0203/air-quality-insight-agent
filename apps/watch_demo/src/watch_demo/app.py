"""The watch demo: a server-rendered watch face, letterboxed, with scenario chips outside it."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .client import AgentClient, client_from_env
from .scenarios import Scenario, load_scenarios
from .why import BAND_LABELS, relative, silence_line, user_tz, why_lines

HERE = Path(__file__).parent
SILENCE_WINDOW = timedelta(hours=12)


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

    def find_user(user_id: str):
        user = next((u for u in client.users() if u.id == user_id), None)
        if user is None:
            raise HTTPException(404, f"unknown user {user_id!r}")
        return user

    def page(request: Request, scenario: Scenario, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "watch.html",
            {"scenarios": scenarios, "scenario": scenario, "band_labels": BAND_LABELS, **ctx},
        )

    @app.get("/", response_class=HTMLResponse)
    def watch(request: Request, scenario: str | None = None):
        sc = pick(scenario)
        try:
            user = find_user(sc.user_id)
            feed = client.feed(sc.user_id, sc.replay_run, sc.until)
            if sc.limit:
                feed = feed[: sc.limit]
            silence = None
            if not feed:
                decisions = client.decisions(
                    sc.user_id, sc.until - SILENCE_WINDOW, sc.until, replay_run=sc.replay_run
                )
                silence = silence_line(decisions, user)
        except httpx.HTTPError as exc:
            return page(request, sc, view="error", error=str(exc), now_local=None)
        cards = [{"n": n, "ago": relative(n.shown_at, sc.until)} for n in feed]
        return page(
            request,
            sc,
            view="feed" if cards else "empty",
            user=user,
            cards=cards,
            silence=silence,
            now_local=sc.until.astimezone(user_tz(user)),
        )

    @app.get("/why/{notification_id}", response_class=HTMLResponse)
    def why(request: Request, notification_id: str, scenario: str | None = None):
        sc = pick(scenario)
        user = find_user(sc.user_id)
        feed = client.feed(sc.user_id, sc.replay_run, sc.until)
        n = next((x for x in feed if x.id == notification_id), None)
        if n is None:
            raise HTTPException(404, f"notification {notification_id!r} not in this scenario")
        try:
            ex = client.explain(notification_id)
        except (KeyError, httpx.HTTPError):
            raise HTTPException(404, f"no explanation for {notification_id!r}")
        return page(
            request,
            sc,
            view="why",
            user=user,
            n=n,
            ago=relative(n.shown_at, sc.until),
            lines=why_lines(n, ex, user),
            decision=ex.decision,
            now_local=sc.until.astimezone(user_tz(user)),
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
