"""Wiring: the two triggers (S-C §7.1). A data run after ingestion, and a clock tick.

Every layer below is a pure function; this module gathers each user's context from the database,
calls the pipeline, and persists the decision, the episode, any held notice and any notification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from aqagent import db, params, repo
from aqagent.act import compose as composer
from aqagent.act.deliver import deliver
from aqagent.act.facts import build_insight
from aqagent.clock import Clock
from aqagent.decide.episode import EpisodeState, timeout_episode
from aqagent.decide.pipeline import (
    REASON_TEXT, Evaluation, UserClockContext, UserHourContext, evaluate_check_in, evaluate_hour, evaluate_release,
)
from aqagent.decide.rules import Rules, load_rules
from aqagent.sense.resolve import station_for
from aqagent.types import Band, Candidate, CandidateKind, EventKind, Outcome, ReasonCode, TraceStep
from aqagent.understand.score import score_hours

HOUR = timedelta(hours=1)
SCORING_LOOKBACK = timedelta(days=params.BASELINE_DAYS) + timedelta(hours=params.SCORE_WINDOW_HOURS + 1)
HISTORY_HOURS = params.BASELINE_DAYS * 24


@dataclass
class RunSummary:
    decisions: int = 0
    sent: int = 0
    held: int = 0
    scored: int = 0

    def add(self, ev: Evaluation) -> None:
        self.decisions += 1
        self.sent += ev.outcome is Outcome.sent
        self.held += ev.outcome is Outcome.held


@dataclass(frozen=True)
class UserRow:
    id: str
    display_name: str
    city: str
    station_id: int
    sensor_id: int
    tz: ZoneInfo
    persona: dict
    rules: Rules
    rules_version: int


# --- episodes ------------------------------------------------------------------------------------

def save_episode(conn: sa.Connection, user_id: str, sensor_id: int, ep: EpisodeState) -> int:
    values = dict(
        user_id=user_id, sensor_id=sensor_id, opened_at=ep.opened_at, closed_at=ep.closed_at, state=ep.state,
        close_reason=ep.close_reason, peak_value=ep.peak_value, peak_band=_slug(ep.peak_band),
        last_notified_at=ep.last_notified_at, last_notified_band=_slug(ep.last_notified_band),
        last_notified_kind=ep.last_notified_kind.value if ep.last_notified_kind else None,
        notifications_sent=ep.notifications_sent, kinds=sorted(k.value for k in ep.kinds), last_hour=ep.last_hour)
    if ep.id is None:
        return conn.execute(db.episodes.insert().values(**values)).inserted_primary_key[0]
    conn.execute(db.episodes.update().where(db.episodes.c.id == ep.id).values(**values))
    return ep.id


def _episode_from_row(r) -> EpisodeState:
    return EpisodeState(
        id=r.id, state=r.state, opened_at=r.opened_at, closed_at=r.closed_at, close_reason=r.close_reason,
        kinds=frozenset(EventKind(k) for k in (r.kinds or [])), peak_value=r.peak_value,
        peak_band=Band.parse(r.peak_band) if r.peak_band else None, last_notified_at=r.last_notified_at,
        last_notified_band=Band.parse(r.last_notified_band) if r.last_notified_band else None,
        last_notified_kind=CandidateKind(r.last_notified_kind) if r.last_notified_kind else None,
        notifications_sent=r.notifications_sent, last_hour=r.last_hour)


def load_episodes(conn: sa.Connection, user_id: str, sensor_id: int) -> tuple[EpisodeState | None, EpisodeState | None]:
    """(the open episode, the most recently closed one)."""
    e = db.episodes
    base = sa.select(e).where(e.c.user_id == user_id, e.c.sensor_id == sensor_id)
    open_row = conn.execute(base.where(e.c.state != "CLOSED").order_by(e.c.id.desc()).limit(1)).first()
    closed_row = conn.execute(base.where(e.c.state == "CLOSED").order_by(e.c.closed_at.desc(), e.c.id.desc()).limit(1)).first()
    return (_episode_from_row(open_row) if open_row else None, _episode_from_row(closed_row) if closed_row else None)


# --- users and history ---------------------------------------------------------------------------

def users_for(conn: sa.Connection, station_id: int | None = None, user_ids: list[str] | None = None) -> list[UserRow]:
    u, s, sn = db.users, db.stations, db.sensors
    q = sa.select(u, s.c.timezone).join(s, s.c.id == u.c.station_id)
    if station_id is not None:
        q = q.where(u.c.station_id == station_id)
    if user_ids is not None:
        q = q.where(u.c.id.in_(user_ids))
    out = []
    for r in conn.execute(q.order_by(u.c.id)).mappings():
        current = repo.current_rules(conn, r["id"])
        version, raw = current if current else (0, None)
        rules, _code = load_rules(raw, None, default_station=r["station_id"])
        station_id = station_for(rules)  # S3 RESOLVE (stub): the one station in the user's rules
        param = rules.pollutants[0]
        sensor_id = conn.execute(sa.select(sn.c.id).where(sn.c.station_id == station_id, sn.c.parameter == param)).scalar()
        if sensor_id is None:
            continue
        out.append(UserRow(r["id"], r["display_name"], r["city"] or "", station_id, sensor_id,
                           ZoneInfo(r["timezone"]), r["persona"] or {}, rules, version))
    return out


def _sent_today_nonsevere(conn: sa.Connection, user: UserRow, at: datetime) -> int:
    local = at.astimezone(user.tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(at.tzinfo)
    n = db.notifications
    rows = conn.execute(sa.select(n.c.context_facts).where(n.c.user_id == user.id, n.c.delivered_at >= start,
                                                             n.c.delivered_at <= at)).all()
    count = 0
    for (facts,) in rows:
        band = ((facts or {}).get("now") or {}).get("band")
        if band is None or not Band.parse(band).is_severe:
            count += 1
    return count


def _last_sent_at(conn: sa.Connection, user_id: str, at: datetime) -> datetime | None:
    n = db.notifications
    return conn.execute(sa.select(sa.func.max(n.c.delivered_at)).where(n.c.user_id == user_id, n.c.delivered_at <= at)).scalar()


def _last_evaluated_hour(conn: sa.Connection, user_id: str) -> datetime | None:
    d = db.decisions
    return conn.execute(sa.select(sa.func.max(d.c.period_end)).where(d.c.user_id == user_id, d.c.trigger == "data",
                                                                    d.c.reason_code != ReasonCode.LATE_HOUR_SCORED.value)).scalar()


# --- persistence of one evaluation -----------------------------------------------------------------

def _persist(conn: sa.Connection, user: UserRow, ev: Evaluation, *, period_end: datetime, at: datetime,
             trigger: Literal["data", "clock"], score_ids: list[int] | None, llm, replay_run: str | None,
             held_ids: list[int] | None = None) -> int:
    episode_id = None
    if ev.episode_after is not None:
        episode_id = save_episode(conn, user.id, user.sensor_id, ev.episode_after)
    trace = [s.as_dict() for s in ev.trace]
    decision_id = conn.execute(db.decisions.insert().values(
        evaluated_at=at, period_end=period_end, user_id=user.id, sensor_id=user.sensor_id,
        rules_version=user.rules_version, episode_id=episode_id, score_ids=score_ids or [],
        outcome=ev.outcome.value, reason_code=ev.reason_code.value, trigger=trigger,
        reason=_reason_sentence(ev), trace=trace, replay_run=replay_run)).inserted_primary_key[0]

    if ev.outcome is Outcome.held and ev.candidate is not None:
        c = replace(ev.candidate, episode_id=episode_id)
        conn.execute(db.held_notices.insert().values(user_id=user.id, decision_id=decision_id,
                                                     candidate=_candidate_out(c), held_at=at))
    if held_ids:
        conn.execute(db.held_notices.update().where(db.held_notices.c.id.in_(held_ids))
                     .values(released_decision_id=decision_id))
    if ev.outcome is Outcome.sent and ev.candidate is not None:
        insight = _insight(conn, user, ev, at, episode_id)
        msg = composer.compose(insight, llm)
        insight["generator_model"] = getattr(llm, "model", None)
        deliver(conn, decision_id=decision_id, user_id=user.id, msg=msg, insight=insight,
                kind=ev.candidate.kind.value, at=at)
    return decision_id


def _insight(conn: sa.Connection, user: UserRow, ev: Evaluation, at: datetime, episode_id: int | None) -> dict:
    score = ev.score
    history = repo.scores_window(conn, user.sensor_id, score.period_end, hours=HISTORY_HOURS, as_of=at)
    m_h = (score.evidence or {}).get("m_h")
    typical = math.expm1(m_h) if isinstance(m_h, (int, float)) else None
    ep = ev.episode_after
    episode = None
    if ep is not None:
        end = ep.closed_at or at
        episode = {"opened_at": ep.opened_at, "peak_value": ep.peak_value,
                   "peak_band": ep.peak_band.slug if ep.peak_band else None, "peak_at": None,
                   "hours": max(1, round((end - ep.opened_at) / HOUR))}
    insight = build_insight(ev.candidate, user={"name": user.display_name, "persona": user.persona}, city=user.city,
                            tz=user.tz, at=at, score=score, typical_pm25=typical, episode=episode,
                            history=history, absorbed_held=list(ev.absorbed))
    insight["episode_id"] = episode_id
    return insight


def _reason_sentence(ev: Evaluation) -> str:
    base = REASON_TEXT.get(ev.reason_code, ev.reason_code.value)
    last = ev.trace[-1] if ev.trace else None
    if ev.reason_code is ReasonCode.QUIET_HOURS_HELD and last is not None and last.values.get("held_until"):
        until = datetime.fromisoformat(last.values["held_until"]).strftime("%H:%M")
        return f"Held: quiet hours until {until}."
    if ev.reason_code is ReasonCode.COOLDOWN and last is not None:
        return f"Too soon: {last.values.get('elapsed_h')}h since the last message, {last.values.get('required_gap_h')}h needed."
    return base


def _candidate_out(c: Candidate) -> dict:
    return {"kind": c.kind.value, "band": _slug(c.band), "episode_id": c.episode_id,
            "event_kind": c.event_kind.value if c.event_kind else None, "severe": c.severe}


def _candidate_in(d: dict) -> Candidate:
    return Candidate(CandidateKind(d["kind"]), Band.parse(d["band"]) if d.get("band") else None, d.get("episode_id"),
                     EventKind(d["event_kind"]) if d.get("event_kind") else None, bool(d.get("severe")))


def _held(conn: sa.Connection, user_id: str) -> tuple[list[int], list[Candidate]]:
    h = db.held_notices
    rows = conn.execute(sa.select(h).where(h.c.user_id == user_id, h.c.released_decision_id.is_(None))
                        .order_by(h.c.id)).mappings().all()
    return [r["id"] for r in rows], [_candidate_in(r["candidate"]) for r in rows]


# --- the two triggers -----------------------------------------------------------------------------

def data_run(conn: sa.Connection, changed: dict[int, list[datetime]], clock: Clock, llm=None,
             replay_run: str | None = None) -> RunSummary:
    """Score every new or revised hour once per sensor, then evaluate each user on that sensor, in order."""
    at = clock.now()
    summary = RunSummary()
    for sensor_id, hours in sorted(changed.items()):
        hours = sorted(set(hours))
        station = conn.execute(sa.select(db.sensors.c.station_id, db.stations.c.timezone)
                               .join(db.stations, db.stations.c.id == db.sensors.c.station_id)
                               .where(db.sensors.c.id == sensor_id)).first()
        if station is None or not hours:
            continue
        tz = ZoneInfo(station.timezone)
        # S-C §2: the newest hour was only provisionally clean; re-check the hour before each arrival.
        recheck = sorted({h - HOUR for h in hours} - set(hours))
        before = {h: s for h in recheck for s in repo.scores_window(conn, sensor_id, h, hours=1, as_of=at)}
        ss = db.station_scores
        done_now = {r for (r,) in conn.execute(sa.select(ss.c.period_end).where(
            ss.c.sensor_id == sensor_id, ss.c.evaluated_at == at, ss.c.period_end.in_(recheck)))} if recheck else set()
        recheck = [h for h in recheck if h in before and h not in done_now]
        known = repo.readings_as_of(conn, sensor_id, min(hours + recheck) - SCORING_LOOKBACK, hours[-1], at)
        scores = score_hours(known, tz, sorted(hours + recheck), at, sensor_id=sensor_id)
        repo.save_scores(conn, scores, at)
        summary.scored += len(scores)
        turned_bad = {s.period_end: s.excluded for s in scores
                      if s.period_end in before and before[s.period_end].excluded is None and s.excluded is not None}

        for user in [u for u in users_for(conn, station.station_id) if u.sensor_id == sensor_id]:
            high_water = _last_evaluated_hour(conn, user.id)
            for hour, code in sorted(turned_bad.items()):
                if high_water is not None and hour <= high_water:
                    ev = Evaluation(Outcome.no_event, code, [TraceStep("S2/U2", False, code, values={
                        "period_end": hour.isoformat(), "rechecked": True})], None)
                    _persist(conn, user, ev, period_end=hour, at=at, trigger="data",
                             score_ids=repo.score_ids_window(conn, sensor_id, hour, hours=1, as_of=at),
                             llm=llm, replay_run=replay_run)
                    summary.add(ev)
            for hour in hours:
                if high_water is not None and hour <= high_water:
                    ev = Evaluation(Outcome.no_event, ReasonCode.LATE_HOUR_SCORED,
                                    [TraceStep("S2/U2", False, ReasonCode.LATE_HOUR_SCORED,
                                               values={"period_end": hour.isoformat(),
                                                       "last_evaluated": high_water.isoformat()})], None)
                    _persist(conn, user, ev, period_end=hour, at=at, trigger="data",
                             score_ids=repo.score_ids_window(conn, sensor_id, hour, hours=1, as_of=at),
                             llm=llm, replay_run=replay_run)
                    summary.add(ev)
                    continue
                window = repo.scores_window(conn, sensor_id, hour, as_of=at)
                if not window or window[-1].period_end != hour:
                    continue
                episode, last_closed = load_episodes(conn, user.id, sensor_id)
                ctx = UserHourContext(user.id, user.rules, user.rules_version, user.tz, window, episode, last_closed,
                                      _sent_today_nonsevere(conn, user, at), _last_sent_at(conn, user.id, at), at)
                ev = evaluate_hour(ctx)
                _persist(conn, user, ev, period_end=hour, at=at, trigger="data",
                         score_ids=repo.score_ids_window(conn, sensor_id, hour, as_of=at), llm=llm,
                         replay_run=replay_run)
                summary.add(ev)
                high_water = hour
    return summary


def clock_tick(conn: sa.Connection, clock: Clock, llm=None,
               event: Literal["hourly", "check_in", "quiet_end"] = "hourly",
               user_ids: list[str] | None = None, replay_run: str | None = None) -> RunSummary:
    """The clock trigger: silent sensors (NO_DATA, 24h timeout), morning check-ins, and quiet-hours release."""
    at = clock.now()
    summary = RunSummary()
    for user in users_for(conn, user_ids=user_ids):
        newest = repo.newest_reading_at(conn, user.sensor_id, at)
        episode, last_closed = load_episodes(conn, user.id, user.sensor_id)
        period_end = newest or at.replace(minute=0, second=0, microsecond=0)

        if event == "hourly":
            silent = newest is None or at - newest > timedelta(hours=params.NO_DATA_HOURS)
            if not silent:
                continue
            closed = timeout_episode(episode, newest, at) if (episode is not None and newest is not None) else episode
            if episode is not None and closed is not None and closed.state == "CLOSED":
                ev = Evaluation(Outcome.no_event, ReasonCode.NO_DATA_TIMEOUT,
                                [TraceStep("D2", False, ReasonCode.NO_DATA_TIMEOUT,
                                           values={"newest_reading_at": newest.isoformat()})], closed)
            else:
                ev = Evaluation(Outcome.no_event, ReasonCode.NO_DATA,
                                [TraceStep("S2/U2", False, ReasonCode.NO_DATA,
                                           values={"newest_reading_at": newest.isoformat() if newest else None,
                                                   "age_h": round((at - newest) / HOUR, 2) if newest else None})], None)
            _persist(conn, user, ev, period_end=period_end, at=at, trigger="clock", score_ids=[], llm=llm,
                     replay_run=replay_run)
            summary.add(ev)
            continue

        window = repo.scores_window(conn, user.sensor_id, newest, as_of=at) if newest else []
        ctx = UserClockContext(user.id, user.rules, user.rules_version, user.tz, window, episode, last_closed,
                               _sent_today_nonsevere(conn, user, at), _last_sent_at(conn, user.id, at), at, newest)
        held_ids, held = _held(conn, user.id)
        if event == "check_in":
            ev = evaluate_check_in(ctx, held)
            release = held_ids if ev.outcome is Outcome.sent else None
        else:
            if not held:
                continue
            ev = evaluate_release(ctx, held)
            release = held_ids
        score_ids = repo.score_ids_window(conn, user.sensor_id, newest, hours=1, as_of=at) if newest else []
        _persist(conn, user, ev, period_end=period_end, at=at, trigger="clock", score_ids=score_ids, llm=llm,
                 replay_run=replay_run, held_ids=release)
        summary.add(ev)
    return summary


def _slug(band: Band | None) -> str | None:
    return band.slug if band is not None else None
