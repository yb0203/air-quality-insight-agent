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


def first_decision(user: str, code: str, start: datetime, end: datetime):
    """The first decision with `code` for `user` evaluated in [start, end], or None."""
    return conn.execute(sa.select(d).where(d.c.user_id == user, d.c.reason_code == code, d.c.replay_run == RUN,
                                           d.c.evaluated_at >= start, d.c.evaluated_at <= end)
                        .order_by(d.c.evaluated_at)).mappings().first()


def kinds(*decision_ids) -> list[str]:
    """Capability keys for the event kinds the real trace says fired (D1), so tags never overclaim."""
    out = []
    for did in decision_ids:
        trace = conn.execute(sa.select(d.c.trace).where(d.c.id == did)).scalar() or []
        for t in trace:
            if t.get("layer") == "D1":
                for k in (t.get("values") or {}).get("fired") or []:
                    if k in ("spike", "climb", "elevated") and k not in out:
                        out.append(k)
    return out


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def need(row, what: str):
    """Every beat must match the replay: stop the export if the expected decision isn't there."""
    if row is None:
        raise SystemExit(f"replay mismatch: expected {what}")
    return row


def tier_one() -> list[dict]:
    """Six more real moments, each beat a decision the replay actually made."""
    out = []

    # Sudden spike: Delhi, 20 Sep. Check-in at 06:30, then a sharp jump to Very Unhealthy sent at once.
    a, b = utc("2026-09-19T20:00"), utc("2026-09-20T09:30")
    chk = need(first_decision("arjun", "SENT_CHECK_IN", a, b), "Arjun's check-in on 20 Sep")
    sev = need(first_decision("arjun", "SENT_SEVERE_BYPASS", chk["evaluated_at"], b), "a severe notice on 20 Sep")
    dup = need(first_decision("arjun", "DEDUP_SAME_BAND", sev["evaluated_at"], b), "a deduped hour after it")
    out.append(export("sudden-spike", "Sudden spike",
                      "Delhi, 20 Sep: already unhealthy at Arjun's check-in, then PM2.5 jumped to very unhealthy "
                      "mid-morning. Severe air is sent at once; the next hours at the same level stay silent.",
                      {"user": "arjun", "start": b - 24 * H, "end": b},
                      story={"group": "speaks", "brief": ["B2b", "B3"],
                             "question": "The air is already bad, then it jumps sharply. Does the agent speak again, and when?",
                             "shows": [*kinds(sev["id"]), "severe", "no-repeats", "message"],
                             "beats": [(chk["evaluated_at"], "Morning check-in", "Unhealthy, worse than a usual morning."),
                                       (sev["evaluated_at"], "Jumped sharply", "Very unhealthy now: sent at once, a full band worse."),
                                       (dup["evaluated_at"], "Same level, silent", "Already told; nothing new to say.")]}))

    # Severe night: Delhi, 17-18 Oct. Very unhealthy at 2:50am breaks through quiet hours; the check-in stays quiet.
    a, b = utc("2026-10-17T18:00"), utc("2026-10-18T03:00")
    sev = need(first_decision("arjun", "SENT_SEVERE_BYPASS", a, b), "a severe notice on the night of 17 Oct")
    dup = need(first_decision("arjun", "DEDUP_SAME_BAND", sev["evaluated_at"], b), "a deduped hour after it")
    quiet = need(first_decision("arjun", "CHECKIN_QUIET", sev["evaluated_at"], b), "a quiet check-in on 18 Oct")
    out.append(export("severe-night", "Severe night",
                      "Delhi, night of 17 Oct: the air reached very unhealthy in the small hours. Quiet hours hold "
                      "ordinary news, not severe air. Having just told him, the 06:30 check-in stays quiet.",
                      {"user": "arjun", "start": b - 24 * H, "end": b},
                      story={"group": "speaks", "brief": ["D8", "B3"],
                             "question": "It's 3am and the air turns very unhealthy. Does the agent wake Arjun?",
                             "shows": ["severe", "quiet-hours", "check-in", "no-repeats"],
                             "beats": [(sev["evaluated_at"], "Breaks through", "Very unhealthy: sent despite quiet hours."),
                                       (dup["evaluated_at"], "Then silent", "Same level, already told."),
                                       (quiet["evaluated_at"], "Check-in stays quiet", "Nothing new since the night's message.")]}))

    # Slow build-up: Los Angeles, 20-21 Aug. No spike, just stuck above normal: one message, then a day of silence.
    a, b = utc("2026-08-20T00:00"), utc("2026-08-21T16:00")
    opened = need(first_decision("maya", "SENT_OPENED", a, b), "an LA notice on 20 Aug")
    later = need(first_decision("maya", "EPISODE_CONTINUES", opened["evaluated_at"] + 20 * H, b), "the same spell a day later")
    out.append(export("slow-build-up", "Slow build-up",
                      "Los Angeles, 20 Aug: PM2.5 drifted to about twice its usual level with no sudden jump. A "
                      "slow-drift detector catches it; the spell then lasts days without another message.",
                      {"user": "maya", "start": b - 36 * H, "end": b}, chart_hours=36,
                      story={"group": "speaks", "brief": ["B2a", "B2d"],
                             "question": "No spike, no sharp climb: the air just sits a bit above normal. Is that missed?",
                             "shows": [*kinds(opened["id"]), "missed", "no-repeats"],
                             "beats": [(opened["evaluated_at"], "Stuck above normal", "Caught by the slow-drift detector."),
                                       (later["evaluated_at"], "A day later, still quiet", "Same spell; one message was enough.")]}))

    # All day bad, one message: Dubai, 1 Sep. Held overnight, released at 07:00, then silent all day.
    a, b = utc("2026-08-31T12:00"), utc("2026-09-01T16:00")
    rel = need(first_decision("omar", "HELD_RELEASED", a, b), "Omar's released notice on 1 Sep")
    held = need(first_decision("omar", "QUIET_HOURS_HELD", rel["evaluated_at"] - 12 * H, rel["evaluated_at"]), "the overnight hold")
    dup = need(first_decision("omar", "DEDUP_SAME_BAND", rel["evaluated_at"] + 5 * H, b), "a deduped hour that afternoon")
    out.append(export("all-day-bad", "All day bad, one message",
                      "Dubai, 1 Sep: unhealthy from the small hours to the evening. Omar has low sensitivity, and "
                      "still gets one message at 07:00, then silence for the rest of the bad day.",
                      {"user": "omar", "start": b - 24 * H, "end": b},
                      story={"group": "quiet", "brief": ["B3", "B5"],
                             "question": "Twelve unhealthy hours in a row. How many messages should that be?",
                             "shows": ["quiet-hours", "no-repeats", "sensitivity", "logged"],
                             "beats": [(held["evaluated_at"], "Held overnight", "Worth saying, but it's quiet hours."),
                                       (rel["evaluated_at"], "One message at 07:00", "Everything held goes out as one."),
                                       (dup["evaluated_at"], "Still bad, still silent", "Same level all day: nothing new to say.")]}))

    # Too short to tell: Bengaluru, 2 Sep, 8pm. One high hour between two normal ones: excluded.
    a, b = utc("2026-09-02T12:00"), utc("2026-09-02T19:00")
    dq = need(first_decision("priya", "DQ_SUSPECT", a, b), "the 2 Sep Bengaluru exclusion")
    out.append(export("too-short", "Too short to tell",
                      "Bengaluru, 2 Sep: PM2.5 read 67 for one evening hour, between 10 and 17. Real or not, one hour "
                      "can't confirm anything, and a false alarm costs trust. The agent says nothing.",
                      {"user": "priya", "start": b - 14 * H, "end": b}, chart_hours=14,
                      story={"group": "bad-data", "brief": ["B2d"],
                             "question": "One high hour, then back to normal. Glitch or real? What should the agent do?",
                             "shows": ["glitch", "missed", "logged"],
                             "beats": [(dq["evaluated_at"], "Excluded", "One hour, 4× its neighbours: not enough to act on.")]}))

    # Sensor went silent: Mumbai, 22-23 Sep. No data: nothing judged, and the open story closes quietly after a day.
    a, b = utc("2026-09-22T00:00"), utc("2026-09-23T06:00")
    nd = need(first_decision("rohan", "NO_DATA", a, b), "NO_DATA for Rohan on 22 Sep")
    to = need(first_decision("rohan", "NO_DATA_TIMEOUT", nd["evaluated_at"], b), "the 24h quiet close")
    out.append(export("sensor-silent", "Sensor went silent",
                      "Mumbai, 22 Sep: the monitor stopped reporting for six days. The agent doesn't guess: it logs "
                      "'no data' every hour and, after a day, closes the open story without a message.",
                      {"user": "rohan", "start": b - 30 * H, "end": b}, chart_hours=30,
                      story={"group": "bad-data", "brief": ["B1", "B6"],
                             "question": "The sensor goes quiet mid-story. What does the agent tell Rohan?",
                             "shows": ["no-data", "logged"],
                             "beats": [(nd["evaluated_at"], "No new readings", "Nothing to judge, so nothing is said."),
                                       (to["evaluated_at"], "Closed quietly", "A day without data: the story ends, no message.")]}))
    return out


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


def export(sid: str, label: str, desc: str, spec: dict, limit: int | None = None, chart_hours: int = 24,
           story: dict | None = None) -> dict:
    user, start, end = spec["user"], spec["start"], spec["end"]
    start = min(start, end - timedelta(hours=chart_hours))
    feed = feed_rows(user, start, end)
    write(OUT / "feeds" / f"{user}__{sid}.json", feed)
    decs = queries.decisions(conn, user_id=user, start=start - 2 * H, end=end, replay_run=RUN)
    traces = dict(conn.execute(sa.select(d.c.id, d.c.trace).where(d.c.id.in_([r["id"] for r in decs]))).all())
    write(OUT / "decisions" / f"{user}__{sid}.json",
          [{**r, "id": f"dec_{r['id']}", "trace": traces.get(r["id"]) or []} for r in decs])
    for row in feed:
        nid = int(row["id"].removeprefix("ntf_"))
        write(OUT / "explain" / f"{row['id']}.json", queries.explain(conn, nid))
    out = {"id": sid, "label": label, "user_id": user, "replay_run": sid, "until": iso(end), "description": desc,
           "chart_hours": chart_hours}
    if limit:
        out["limit"] = limit
    if story:
        beats = [{"at": iso(at), "title": title, "note": note} for at, title, note in story.pop("beats", [])]
        out.update(story)
        out["beats"] = [b for b in beats if start <= datetime.fromisoformat(b["at"].replace("Z", "+00:00")) <= end]
    print(f"{sid:16} {user:6} {iso(start)} → {iso(end)}  notices={len(feed)} decisions={len(decs)}")
    return out


if __name__ == "__main__":
    smog, glitch, quiet, smoke = find_smog_night(), find_glitch(), find_quiet_night(), helsinki_smoke()
    if OUT.exists():
        shutil.rmtree(OUT)
    write(OUT / "users.json", queries.list_users(conn))
    export_readings()
    ist = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
    chk, clr = smog["check_in"]["delivered_at"], smog["cleared"]["delivered_at"]
    c_local = chk.astimezone(ist)
    held = first_decision("arjun", "QUIET_HOURS_HELD", chk - 12 * H, chk)
    cont = first_decision("arjun", "EPISODE_CONTINUES", held["evaluated_at"], chk) if held else None
    smog_beats = ([(held["evaluated_at"], "Held overnight", "Worth telling Arjun, but it's quiet hours.")] if held else []) + [
        *([(cont["evaluated_at"], "Silent, same story", "The bad spell continues; nothing new to say.")] if cont else []),
        (chk, "One check-in", "At 06:30 the held notice folds into one message."),
        (clr, "All-clear", "The spell is over and was long enough to be worth saying."),
    ]
    smoke_n = notes("aino", smoke["start"], smoke["end"])[-1]
    smoke_note, smoke_dec = smoke_n["delivered_at"], smoke_n["decision_id"]
    glitch_dec = first_decision("rohan", "DQ_SUSPECT", glitch["glitch"], glitch["end"])
    quiet_chk = first_decision("priya", "CHECKIN_QUIET", quiet["start"], quiet["end"])
    scenarios = [
        export("delhi-smog-night", "Delhi smog night",
               f"The air turned bad overnight; the notice was held through quiet hours and folded into one check-in "
               f"at {c_local:%H:%M} on {c_local:%-d %b}, then an all-clear once it eased.", smog,
               story={"group": "speaks", "brief": ["B2a", "B3"],
                      "question": "Arjun runs at 06:30 and the air turns bad overnight. How does the agent avoid "
                                  "waking him, yet still warn him before his run?",
                      "shows": [*kinds(held["id"]), "quiet-hours", "check-in", "no-repeats", "clearing"],
                      "beats": smog_beats}),
        export("back-to-normal", "Back to normal",
               "The same Delhi episode closing: the all-clear is only sent after a genuinely bad period.", smog, limit=1,
               story={"group": "speaks", "brief": ["B2c"],
                      "question": "When the bad spell ends, is it worth a message? Only if it was long or bad enough.",
                      "shows": ["clearing", "message"],
                      "beats": [(clr, "All-clear", "Sent with one suggestion for the better air.")]}),
        export("helsinki-smoke", "Helsinki smoke",
               "Smoke took Helsinki to ~27 µg/m³ against a usual ~4 on 24 Aug: still 'Moderate', "
               "but very unusual here, so it's worth a heads-up.", smoke,
               story={"group": "per-person", "brief": ["B2", "B5"],
                      "question": "Aino has asthma. The official scale says 'Moderate'. Should she hear about it?",
                      "shows": ["baseline", "sensitivity", *kinds(smoke_dec), "message"],
                      "beats": [(smoke_note, "Heads-up", "Six times Helsinki's usual: unusual here, and Aino is sensitive.")]}),
        export("glitch-ignored", "Glitch ignored",
               f"Mumbai's monitor reported one implausible hour ({iso(glitch['glitch'])}). OpenAQ didn't flag it; "
               "the agent excluded it as a glitch and said nothing.", glitch, chart_hours=14,
               story={"group": "bad-data", "brief": ["B2d"],
                      "question": "A sensor reports one absurd hour. Does the agent raise an alarm?",
                      "shows": ["glitch", "logged"],
                      "beats": [(glitch_dec["evaluated_at"], "Glitch ignored",
                                 "One absurd hour between two normal ones: excluded, and nothing sent.")]
                                if glitch_dec else []}),
        export("quiet-night", "Quiet night",
               "Nothing worth saying: Priya's 06:00 check-in found Bengaluru's night cleaner than usual.", quiet,
               story={"group": "quiet", "brief": ["B6"],
                      "question": "A normal night. The agent says nothing, but can it still tell you why?",
                      "shows": ["logged", "check-in"],
                      "beats": [(need(first_decision("priya", "NO_TRIGGER", quiet["start"] + 2 * H, quiet["end"]),
                                      "a logged quiet hour")["evaluated_at"],
                                 "Every hour logged", "Nothing unusual, and the reason is recorded."),
                                *([(quiet_chk["evaluated_at"], "Check-in stays quiet", "Nothing worse than usual, so no message.")]
                                  if quiet_chk else [])]}),
    ]
    scenarios += tier_one()
    SCENARIOS.write_text("# Generated by scripts/export_watch_fixtures.py from the real 90-day replay (data/replay.db).\n"
                         "# Each scenario's `replay_run` names its own fixture files; `until` is the replayed 'now'.\n"
                         + yaml.safe_dump({"scenarios": scenarios}, sort_keys=False, allow_unicode=True, width=110))
    print(f"wrote {OUT} and {SCENARIOS}")
