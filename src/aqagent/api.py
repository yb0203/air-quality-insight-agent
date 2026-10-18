"""FastAPI app: health, users, feed, decisions, explain, feedback, export.

The JSON shapes are a contract with the watch-demo app. Datetimes are ISO 8601 UTC strings; naive datetimes in
query parameters are read as UTC.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from aqagent import queries
from aqagent.clock import Clock
from aqagent.learn import feedback

UTC = timezone.utc


class FeedbackIn(BaseModel):
    action: feedback.Action


def _utc(t: datetime | None) -> datetime | None:
    if t is None:
        return None
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _iso(obj):
    """Recursively render datetimes as ISO 8601 UTC strings."""
    if isinstance(obj, datetime):
        return _utc(obj).isoformat()
    if isinstance(obj, dict):
        return {k: _iso(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_iso(v) for v in obj]
    return obj


def _json(obj, status_code: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder(_iso(obj)), status_code=status_code)


def create_app(engine: Engine, clock: Clock) -> FastAPI:
    app = FastAPI(title="aqagent")

    def require_user(conn, user_id: str) -> None:
        if not queries.user_exists(conn, user_id):
            raise HTTPException(404, f"unknown user {user_id!r}")

    @app.get("/health")
    def health():
        try:
            with engine.connect() as conn:
                sensors = queries.sensor_freshness(conn, clock.now())
        except SQLAlchemyError:
            return _json({"ok": False, "sensors": []}, status_code=503)
        return _json({"ok": True, "sensors": sensors})

    @app.get("/users")
    def users():
        with engine.connect() as conn:
            return _json(queries.list_users(conn))

    @app.get("/users/{user_id}/feed")
    def feed(user_id: str, replay_run: str | None = None, until: datetime | None = None):
        with engine.connect() as conn:
            require_user(conn, user_id)
            return _json(queries.feed(conn, user_id, replay_run=replay_run, until=_utc(until)))

    @app.get("/decisions")
    def decisions(user_id: str | None = None, start: datetime | None = None, end: datetime | None = None,
                  outcome: str | None = None, replay_run: str | None = None):
        with engine.connect() as conn:
            return _json(queries.decisions(conn, user_id=user_id, start=_utc(start), end=_utc(end),
                                           outcome=outcome, replay_run=replay_run))

    @app.get("/notifications/{notification_id}/explain")
    def explain(notification_id: int):
        with engine.connect() as conn:
            out = queries.explain(conn, notification_id)
        if out is None:
            raise HTTPException(404, f"unknown notification {notification_id}")
        return _json(out)

    @app.post("/notifications/{notification_id}/feedback", status_code=201)
    def post_feedback(notification_id: int, body: FeedbackIn):
        with engine.begin() as conn:
            owner = queries.notification_user(conn, notification_id)
            if owner is None:
                raise HTTPException(404, f"unknown notification {notification_id}")
            fid = feedback.record(conn, notification_id, owner, body.action, clock.now())
        return _json({"id": fid}, status_code=201)

    @app.get("/users/{user_id}/export")
    def export(user_id: str, replay_run: str | None = None):
        with engine.connect() as conn:
            require_user(conn, user_id)
            rows = queries.export_rows(conn, user_id, replay_run=replay_run)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=queries.EXPORT_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(_iso(r))
        return Response(buf.getvalue(), media_type="text/csv")

    return app
