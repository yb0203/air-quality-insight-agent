"""Seed stations and demo users. Users come from config/users.yaml; their raw rules become rules version 1."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
import yaml

from aqagent import db, repo
from aqagent.decide.rules import load_users

DEFAULT_USERS = Path(__file__).resolve().parents[2] / "config" / "users.yaml"


def seed_users(conn: sa.Connection, at: datetime, path: str | Path = DEFAULT_USERS) -> int:
    load_users(path)  # validates every entry first: our own config must be correct
    raw = (yaml.safe_load(Path(path).read_text()) or {}).get("users", [])
    for entry in raw:
        station_id = entry["rules"]["location"]["station_id"]
        if conn.execute(sa.select(db.stations.c.id).where(db.stations.c.id == station_id)).first() is None:
            continue  # station not loaded in this database
        repo.upsert_user(conn, id=entry["id"], display_name=entry["display_name"], station_id=station_id,
                         persona=entry.get("persona") or {}, city=entry.get("city"))
        current = repo.current_rules(conn, entry["id"])
        if current is None or current[1] != entry["rules"]:
            repo.save_rules(conn, entry["id"], entry["rules"], "user", at)
    return len(raw)
