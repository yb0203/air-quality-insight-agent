"""Extract the real numbers and text the video shows into composition/assets/{beatmap,data}.js.

Reads (never writes) a checkout that has the built agent: the 90-day sample, the replay
database and the watch demo fixtures. By default that is the main checkout of this repo.

    uv run --project <repo>/apps/watch_demo python docs/demo/video/scripts/build_assets.py [--repo <path>]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VIDEO = Path(__file__).resolve().parents[1]
ASSETS = VIDEO / "composition" / "assets"

TRACKED = [  # (city, OpenAQ location id), clean to dusty, as in the design
    ("Helsinki", 4588),
    ("Los Angeles", 7936),
    ("Bengaluru", 6206921),
    ("Dubai", 6096447),
    ("Delhi", 4712609),
]
MUMBAI = 8039
IST = ZoneInfo("Asia/Kolkata")


def default_repo() -> Path:
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=VIDEO, capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def sample_facts(repo: Path) -> dict:
    by_loc: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    with open(repo / "data" / "samples" / "openaq_pm25_hourly_90d.csv") as f:
        for r in csv.DictReader(f):
            by_loc[int(r["location_id"])].append((parse(r["period_end_utc"]), float(r["value_ugm3"])))
    cities = [{"city": c, "median": round(statistics.median(v for _, v in by_loc[loc]), 1)} for c, loc in TRACKED]

    # The Mumbai glitch: the 980 hour on 14 October and the hours either side, in local time.
    rows = sorted(by_loc[MUMBAI])
    i = next(k for k, (_, v) in enumerate(rows) if v >= 900)
    mumbai = [{"t": t.astimezone(IST).strftime("%H:%M"), "v": round(v)} for t, v in rows[i - 2:i + 3]]
    glitch_day = rows[i][0].astimezone(IST).strftime("%-d %B")
    return {"cities": cities, "mumbai": mumbai, "mumbai_day": glitch_day}


def replay_facts(repo: Path) -> dict:
    db = repo / "data" / "replay.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    run = con.execute("select replay_run from decisions group by replay_run order by count(*) desc").fetchone()[0]
    lo, hi = (parse(x.replace(" ", "T") + "+00:00" if "+" not in x else x)
              for x in con.execute("select min(period_end), max(period_end) from decisions where replay_run=?", (run,)).fetchone())
    weeks = (hi - lo) / timedelta(days=7)
    total_decisions = con.execute("select count(*) from decisions where replay_run=?", (run,)).fetchone()[0]
    users = {uid: (city, loc) for uid, city, loc in con.execute("select id, city, station_id from users")}
    sens = {}
    for uid, rules in con.execute("select user_id, rules from user_rules order by version"):
        try:
            sens[uid] = json.loads(rules).get("sensitivity", "default")
        except (TypeError, ValueError):
            sens[uid] = "default"
    per_user = {}
    for uid, kind, n in con.execute(
            "select d.user_id, n.kind, count(*) from decisions d join notifications n on n.decision_id = d.id "
            "where d.replay_run=? and d.outcome='sent' group by d.user_id, n.kind", (run,)):
        per_user.setdefault(uid, {})[kind] = n
    weekly = []
    for city, loc in TRACKED:
        for uid, (ucity, uloc) in users.items():
            if uloc != loc:
                continue
            kinds = per_user.get(uid, {})
            total = sum(kinds.values())
            weekly.append({"user": uid, "city": city, "sensitivity": sens.get(uid, "default"),
                           "per_week": round(total / weeks, 1),
                           "events_per_week": round((total - kinds.get("check_in", 0)) / weeks, 1)})
    notices = sum(sum(k.values()) for k in per_user.values())
    return {"run": run, "weeks": round(weeks, 1), "decisions": total_decisions, "notices": notices, "weekly": weekly}


def watch_facts(repo: Path) -> dict:
    sys.path.insert(0, str(repo / "apps" / "watch_demo" / "src"))
    from watch_demo.client import FixtureAgentClient  # noqa: E402
    from watch_demo.why import why_lines  # noqa: E402

    from watch_demo.scenarios import load_scenarios  # noqa: E402

    app = repo / "apps" / "watch_demo"
    sc = next(s for s in load_scenarios(app / "scenarios.yaml") if s.id == "delhi-smog-night")
    fx = FixtureAgentClient(app / "fixtures")
    user = next(u for u in fx.users() if u.id == sc.user_id)
    feed = fx.feed(sc.user_id, sc.replay_run, sc.until)
    check_in = next(n for n in feed if n.kind == "check_in")
    ex = fx.explain(check_in.id)
    lines = why_lines(check_in, ex, user)
    trace = [{"layer": t.layer, "passed": t.passed, "code": t.reason_code, "values": t.values} for t in ex.trace]
    # The night around the check-in: 16:00 the day before to the end of the scenario, local time.
    sent_at = check_in.created_at if isinstance(check_in.created_at, datetime) else parse(str(check_in.created_at))
    night = fx.decisions(sc.user_id, sent_at - timedelta(hours=14), sc.until, replay_run=sc.replay_run)
    rows = [{"t": d.evaluated_at.astimezone(IST).strftime("%H:%M"), "outcome": d.outcome,
             "code": d.reason_code, "reason": d.reason} for d in sorted(night, key=lambda d: d.evaluated_at)]
    return {
        "user": {"id": user.id, "name": user.id.capitalize(), "city": user.city},
        "check_in": {"id": check_in.id, "body": check_in.body, "action": check_in.next_action, "band": check_in.band,
                     "t": sent_at.astimezone(IST).strftime("%H:%M")},
        "cleared": next(({"body": n.body, "action": n.next_action} for n in feed if n.kind == "cleared"), None),
        "why": lines,
        "trace": trace,
        "night": rows,
        "night_utc": [{"utc": d.evaluated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "code": d.reason_code}
                      for d in sorted(night, key=lambda d: d.evaluated_at)],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=None, help="checkout with the built agent (default: main checkout)")
    repo = (ap.parse_args().repo or default_repo()).resolve()

    beatmap = json.loads((VIDEO / "beatmap.json").read_text())
    data = {"source_repo_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                                                 capture_output=True, text=True).stdout.strip()}
    data |= sample_facts(repo)
    try:
        data |= {"replay": replay_facts(repo)}
    except sqlite3.OperationalError as exc:  # the replay is being re-run: keep the last good numbers
        old = (ASSETS / "data.js").read_text()
        data |= {"replay": json.loads(old[old.index("=") + 1:].strip().rstrip(";"))["replay"]}
        print(f"warning: replay.db unavailable ({exc}); kept the previous replay numbers", file=sys.stderr)
    data |= {"watch": watch_facts(repo)}

    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "beatmap.js").write_text("window.BEATMAP = " + json.dumps(beatmap, indent=1) + ";\n")
    (ASSETS / "data.js").write_text("window.DATA = " + json.dumps(data, indent=1, ensure_ascii=False) + ";\n")
    print(json.dumps(data, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
