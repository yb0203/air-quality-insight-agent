"""Export real replay results as the watch demo's fixtures, one scenario per chip.

Reads data/replay.db (run scripts/replay_sample.py first), finds five real moments, and writes
apps/watch_demo/fixtures/ + apps/watch_demo/scenarios.yaml.   uv run python scripts/export_watch_fixtures.py
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa
import yaml

from aqagent import db, queries

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "watch_demo" / "fixtures"
SCENARIOS = ROOT / "apps" / "watch_demo" / "scenarios.yaml"
RUN = "demo"
UTC = timezone.utc
H = timedelta(hours=1)

engine = db.make_engine(f"sqlite:///{ROOT / 'data' / 'replay.db'}")
conn = engine.connect()
d, n = db.decisions, db.notifications


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def notes(user: str, start: datetime, end: datetime) -> list[dict]:
    rows = conn.execute(sa.select(n).where(n.c.user_id == user, n.c.delivered_at >= start, n.c.delivered_at <= end)
                        .order_by(n.c.delivered_at.desc())).mappings().all()
    return [dict(r) for r in rows]


def find_smog_night() -> dict:
    """A real Delhi check-in that absorbed a held overnight notice, later followed by an all-clear."""
    for r in conn.execute(sa.select(n).where(n.c.user_id == "arjun", n.c.kind == "check_in")
                          .order_by(n.c.delivered_at)).mappings():
        if not (r["context_facts"] or {}).get("absorbed_held"):
            continue
        cleared = conn.execute(sa.select(n).where(n.c.user_id == "arjun", n.c.kind == "cleared",
                                                  n.c.delivered_at > r["delivered_at"],
                                                  n.c.delivered_at <= r["delivered_at"] + 30 * H)
                               .order_by(n.c.delivered_at)).mappings().first()
        if cleared:
            return {"user": "arjun", "start": r["delivered_at"] - 10 * H, "end": cleared["delivered_at"] + H,
                    "check_in": r, "cleared": cleared}
    raise SystemExit("no Delhi check-in with an absorbed overnight notice followed by an all-clear")


def find_glitch() -> dict:
    """A Mumbai glitch hour with no notice anywhere near it."""
    for (pe,) in conn.execute(sa.select(d.c.period_end).where(d.c.user_id == "rohan", d.c.reason_code == "DQ_SUSPECT")
                              .order_by(d.c.period_end.desc())):
        start, end = pe - 8 * H, pe + 3 * H
        if not notes("rohan", start, end):
            return {"user": "rohan", "start": start, "end": end, "glitch": pe}
    raise SystemExit("no quiet Mumbai glitch window found")


def find_quiet_night() -> dict:
    """Priya's morning check-in that found nothing worse than usual, after a night with no notices."""
    for (at,) in conn.execute(sa.select(d.c.evaluated_at).where(d.c.user_id == "priya", d.c.reason_code == "CHECKIN_QUIET")
                              .order_by(d.c.evaluated_at.desc())):
        if not notes("priya", at - 14 * H, at + H):
            return {"user": "priya", "start": at - 9 * H, "end": at + H}
    raise SystemExit("no quiet Bengaluru night found")


def helsinki_smoke() -> dict:
    start, end = datetime(2026, 8, 23, 22, tzinfo=UTC), datetime(2026, 8, 24, 12, tzinfo=UTC)
    if not notes("aino", start, end):
        raise SystemExit("Aino got no notice for the 24 Aug smoke")
    return {"user": "aino", "start": start, "end": end}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")


def feed_rows(user: str, start: datetime, end: datetime) -> list[dict]:
    rows = [r for r in queries.feed(conn, user, replay_run=RUN, until=end) if datetime.fromisoformat(
        str(r["delivered_at"]).replace("Z", "+00:00")) >= start]
    return [{**r, "id": f"ntf_{r['id']}", "decision_id": f"dec_{r['decision_id']}"} for r in rows]


def export_readings() -> None:
    """readings/<station_id>.json for the chart: hourly value, NowCast, band, usual level and data-quality flag."""
    import math

    ss, sn = db.station_scores, db.sensors
    for station_id, sensor_id in conn.execute(sa.select(sn.c.station_id, sn.c.id).where(sn.c.parameter == "pm25")):
        latest = {}
        for r in conn.execute(sa.select(ss).where(ss.c.sensor_id == sensor_id).order_by(ss.c.period_end, ss.c.evaluated_at)).mappings():
            latest[r["period_end"]] = r
        rows = []
        for pe, r in sorted(latest.items()):
            ev = r["evidence"] or {}
            m_h = ev.get("m_h")
            rows.append({"at": iso(pe), "pm25": ev.get("value"), "nowcast": r["nowcast"], "band": r["band"],
                         "typical_pm25": round(math.expm1(m_h), 1) if isinstance(m_h, (int, float)) else None,
                         "dq": r["excluded"]})
        if rows:
            write(OUT / "readings" / f"{station_id}.json", rows)


def export(sid: str, label: str, desc: str, spec: dict, limit: int | None = None, chart_hours: int = 24) -> dict:
    user, start, end = spec["user"], spec["start"], spec["end"]
    start = min(start, end - timedelta(hours=chart_hours))
    feed = feed_rows(user, start, end)
    write(OUT / "feeds" / f"{user}__{sid}.json", feed)
    decs = queries.decisions(conn, user_id=user, start=start - 2 * H, end=end, replay_run=RUN)
    write(OUT / "decisions" / f"{user}__{sid}.json",
          [{**r, "id": f"dec_{r['id']}"} for r in decs])
    for row in feed:
        nid = int(row["id"].removeprefix("ntf_"))
        write(OUT / "explain" / f"{row['id']}.json", queries.explain(conn, nid))
    out = {"id": sid, "label": label, "user_id": user, "replay_run": sid, "until": iso(end), "description": desc,
           "chart_hours": chart_hours}
    if limit:
        out["limit"] = limit
    print(f"{sid:16} {user:6} {iso(start)} → {iso(end)}  notices={len(feed)} decisions={len(decs)}")
    return out


if __name__ == "__main__":
    smog, glitch, quiet, smoke = find_smog_night(), find_glitch(), find_quiet_night(), helsinki_smoke()
    if OUT.exists():
        shutil.rmtree(OUT)
    write(OUT / "users.json", queries.list_users(conn))
    export_readings()
    c_local = smog["check_in"]["delivered_at"].astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
    scenarios = [
        export("delhi-smog-night", "Delhi smog night",
               f"Arjun runs at 06:30. The air turned bad overnight; the notice was held through quiet hours and "
               f"folded into one check-in at {c_local:%H:%M} on {c_local:%-d %b}, then an all-clear once it eased.", smog),
        export("back-to-normal", "Back to normal",
               "The same Delhi episode closing: the all-clear is only sent after a genuinely bad period.", smog, limit=1),
        export("helsinki-smoke", "Helsinki smoke",
               "Aino has asthma. Smoke took Helsinki to ~27 µg/m³ against a usual ~4 on 24 Aug: still 'Moderate', "
               "but very unusual here, so it's worth a heads-up.", smoke),
        export("glitch-ignored", "Glitch ignored",
               f"Mumbai's monitor reported one implausible hour ({iso(glitch['glitch'])}). OpenAQ didn't flag it; "
               "the agent excluded it as a glitch and said nothing.", glitch, chart_hours=14),
        export("quiet-night", "Quiet night",
               "Nothing worth saying: Priya's 06:00 check-in found Bengaluru's night cleaner than usual.", quiet),
    ]
    SCENARIOS.write_text("# Generated by scripts/export_watch_fixtures.py from the real 90-day replay (data/replay.db).\n"
                         "# Each scenario's `replay_run` names its own fixture files; `until` is the replayed 'now'.\n"
                         + yaml.safe_dump({"scenarios": scenarios}, sort_keys=False, allow_unicode=True, width=110))
    print(f"wrote {OUT} and {SCENARIOS}")
