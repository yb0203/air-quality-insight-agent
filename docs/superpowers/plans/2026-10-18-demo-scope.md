# Air Quality Insight Agent — Demo Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the demo-scope agent: hourly OpenAQ ingestion for 5 cities, a learned per-station detector, the per-user decision pipeline D1–D8, natural-language notices, a decision log with an explain API, and a replay harness that reports caught vs missed.

**Architecture:** A single Python package. Pure functions per layer (S2, U1, U2, D1–D8, A1), wired by a runner that has two triggers: a data run after ingestion, and a clock tick. All state lives in SQL (SQLite locally, Postgres when hosted) through SQLAlchemy Core. Time is always injected. Every evaluation recomputes from the readings known at that moment, so replay equals live.

**Tech Stack:** Python 3.13 · uv · SQLAlchemy 2 (Core) · pydantic 2 · httpx · FastAPI + uvicorn · APScheduler 3.x (scheduling and cron parsing) · anthropic SDK (optional) · ruptures (eval extra) · pytest.

**Spec:** [docs/explainer.md](../../explainer.md) (design, closed) · [docs/specs/S-C-rule-engine-spec.md](../../specs/S-C-rule-engine-spec.md) (exact logic and parameters) · [docs/specs/S-A-openaq-and-schema.md](../../specs/S-A-openaq-and-schema.md) (API facts, schema) · [docs/requirements.md](../../requirements.md) · [docs/QA.csv](../../QA.csv) (test cases)

## Global Constraints

- Python `>=3.12` (3.13 locally). Package `aqagent` in `src/aqagent/`. Tests in `tests/`, named `test_<qa id>_<what>` (e.g. `test_qa_ing_10_band_boundaries`), so every test traces to a QA.csv row.
- Runtime dependencies are limited to: `sqlalchemy>=2`, `pydantic>=2`, `httpx`, `fastapi`, `uvicorn`, `apscheduler>=3.10,<4`. Optional extras: `llm = ["anthropic"]`, `eval = ["ruptures", "numpy"]`. Dev: `pytest`. Statistics use the standard library only.
- Every timestamp is a timezone-aware UTC `datetime`. Local time is derived from `stations.timezone` with `zoneinfo`.
- **No code under `src/aqagent/` except `clock.py` may call `datetime.now`, `datetime.utcnow`, `time.time` or `date.today`** (QA-EVAL-05).
- Every parameter value comes from `src/aqagent/params.py`, copied verbatim from S-C §13. No magic numbers elsewhere.
- Reason codes are exactly those in S-C §10, plus `LATE_HOUR_SCORED` (see "Spec additions" below). Define them once, as `ReasonCode` in `src/aqagent/types.py`.
- Env vars: `OPENAQ_API_KEY` (required for live ingestion, never logged), `DATABASE_URL` (default `sqlite:///data/aqagent.db`), `ANTHROPIC_API_KEY` (optional), `AQAGENT_LLM_MODEL` (default `claude-haiku-5-5`).
- Notice body ≤ 220 characters, exactly one next action, no bare "AQI is now <n>" status (S-C §9).
- Commit after every task with a `feat:` / `test:` / `chore:` message ending in the Co-Authored-By line from the repo's convention.

## Spec additions (confirm, then propagate explainer-first)

These are implementation-level clarifications the specs don't settle. They're used by this plan and must be added to the explainer and S-C after the user confirms.

1. **Late hours older than a user's last evaluated hour** are scored and stored (so they shape every later window) but don't re-run D2–D8 for that past hour. The decision is written as `no_event · LATE_HOUR_SCORED`. In the common case of a sensor outage, all late hours are newer than the last evaluated hour, so they *are* evaluated in order, as the explainer says.
2. **A clock tick writes `NO_DATA`** for a user only when the newest reading is more than 3 h old. Otherwise the tick does only its scheduled work (check-in, release). Every hour still ends up with a decision: either its reading arrives and is evaluated, or the clock records `NO_DATA`.
3. **APScheduler** is the cron library: `CronTrigger.from_crontab(expr, timezone=tz)` for check-ins, live and in replay.

## Review Focus

1. **A late, out-of-order hour** (hour H arrives after H+1..H+3 were evaluated) must not double-count episode transitions or re-send anything. Pinned in Task 10: `test_review_late_hour_does_not_rewind_episode`.
2. **DST transitions** in Helsinki and Los Angeles: the repeated or skipped local hour must not crash hour-of-day bucketing, and quiet hours must follow wall-clock time. Pinned in Task 5: `test_review_dst_hour_buckets`.
3. **A hanging or slow LLM** must not stall the hourly run: 10 s timeout, then the template fallback. Pinned in Task 11: `test_review_llm_timeout_falls_back`.
4. **Overlapping runs** (a slow run still going when the next tick fires) must not double-ingest or double-send. Pinned in Task 14: `test_review_scheduler_no_overlap`.
5. **A station or sensor disappears** from OpenAQ (404 or empty results): the run is partial, the sensor goes down the NO_DATA path, and nothing crashes. Pinned in Task 3: `test_review_sensor_404_is_partial`.

---

## File structure

```
pyproject.toml                         uv project, deps, extras, pytest config
config/users.yaml                      seeded demo users (personas + rules), one or two per city
src/aqagent/
  params.py        all S-C §13 parameters
  types.py         shared dataclasses/enums: Band, EventKind, ReasonCode, Reading, StationScore, TraceStep, ...
  clock.py         Clock protocol, SystemClock, FixedClock (the only module allowed to read wall time)
  db.py            SQLAlchemy Core tables (S-A §5 + station_scores) and an engine factory
  repo.py          data access: readings with revisions, as-of reads, scores, episodes, decisions, notices
  sense/openaq.py  OpenAQ v3 client (S1): hours, rate limits
  sense/ingest.py  ingestion run: trailing window, backfill, revisions, ingestion_runs
  sense/validate.py  S2 data-quality checks (pure)
  sense/resolve.py   S3 stub: user -> station
  understand/aqi.py       NowCast + EPA 2024 bands
  understand/baseline.py  U1 hour-of-day robust baseline
  understand/score.py     U2 station scores
  decide/rules.py      user rules model, defaults, validation
  decide/trigger.py    D1
  decide/episode.py    D2 state machine
  decide/restraint.py  D3 worth it, D4 pace, D5 arbitrate (stub), D6 respond (stub), D7 budget (stub), D8 timing
  decide/pipeline.py   per-user evaluation for one hour / one clock event -> Evaluation (decision + trace + effects)
  act/facts.py     insight builder and history facts
  act/compose.py   LLM composer + validator + template fallback
  act/deliver.py   A2 stub: write the notice to the feed
  learn/feedback.py  L1 record feedback
  runner.py        data run + clock tick orchestration
  api.py           FastAPI app: feed, decisions, explain, feedback, export, health
  replay/load.py   load data/samples into readings with synthetic ingested_at (as-known)
  replay/harness.py  simulated clock, replay run, report
  replay/labels.py   reference moments (ruptures PELT + hand labels)
  cli.py           `aqagent` commands
tests/             one file per module, plus tests/fixtures.py (synthetic series builders)
data/labels.yaml   hand labels for the harness
```

---

### Task 1: Project skeleton, parameters, clock and shared types

**Files:**
- Create: `pyproject.toml`, `src/aqagent/__init__.py`, `src/aqagent/params.py`, `src/aqagent/types.py`, `src/aqagent/clock.py`, `tests/fixtures.py`, `tests/test_foundation.py`
- Modify: `.gitignore` (add `data/aqagent.db`, `.venv/`, `__pycache__/`, `.pytest_cache/`)

**Interfaces:**
- Produces:
  - `params`: module constants named after S-C §13, e.g. `BASELINE_DAYS = 14`, `MIN_HISTORY_HOURS = 72`, `MAD_FLOOR = 0.15`, `LOW_COVERAGE_PCT = 75`, `GLITCH_RATIO = 3`, `GLITCH_DELTA = 20`, `GAP_RESET_HOURS = 3`, `SPIKE_Z = 3.5`, `SPIKE_CONFIRM = (2, 3)`, `EWMA_LAMBDA = 0.3`, `CLIMB_BAR = 1.26`, `CLIMB_HOURS = 3`, `CLIMB_SLOPE = 0.01`, `CUSUM_KREF = 0.5`, `ELEVATED_H = 8`, `ELEVATED_MIN_EWMA = 0.5`, `CALM_EWMA = 0.5`, `CALM_HOURS = 4`, `FLAP_HOURS = 6`, `NO_DATA_TIMEOUT_HOURS = 24`, `CLEAR_MIN_HOURS = 12`, `PACE_BASE_HOURS = 6`, `BUDGET_PER_DAY = 3`, `CHECKIN_WINDOW_HOURS = 8`, `CHECKIN_MIN_GAP_HOURS = 6`, `NEAR_MISS_FRACTION = 0.8`, `SENSITIVITY_K = {"low": 1.25, "default": 1.0, "high": 0.75}`, `STUCK_HOURS = 6`, `INVALID_MAX = 1000`, `SCORE_WINDOW_HOURS = 72`, `MESSAGE_MAX_CHARS = 220`, `LLM_TIMEOUT_S = 10`.
  - `types.Band` (ordered `IntEnum`: GOOD=0, MODERATE, USG, UNHEALTHY, VERY_UNHEALTHY, HAZARDOUS, with `Band.parse("very_unhealthy")` and `.slug`). `Band.is_severe` is True for VERY_UNHEALTHY and above.
  - `types.EventKind` (`StrEnum`: spike, climb, elevated, floor). `types.CandidateKind` (opened, escalated, cleared, check_in, released). `types.Outcome` (sent, held, suppressed, no_event). `types.ReasonCode` (`StrEnum`, every code in S-C §10 plus `LATE_HOUR_SCORED`).
  - Frozen dataclasses: `Reading(sensor_id:int, period_end:datetime, period_start:datetime, value:float|None, coverage_pct:float|None)`, `TraceStep(layer:str, passed:bool, reason_code:ReasonCode|None, inputs:dict, values:dict)`.
  - `clock.Clock` (Protocol: `now() -> datetime`), `SystemClock`, `FixedClock(t)` with `.advance(timedelta)`.
  - `tests/fixtures.py`: `hourly(start, values, sensor_id=1, coverage=100.0) -> list[Reading]`, `UTC`.

- [ ] **Step 1: Write the failing tests** in `tests/test_foundation.py`

```python
def test_params_match_spec():
    assert (params.SPIKE_Z, params.CLIMB_BAR, params.ELEVATED_H, params.CALM_HOURS) == (3.5, 1.26, 8, 4)
    assert params.SENSITIVITY_K == {"low": 1.25, "default": 1.0, "high": 0.75}
    assert (params.PACE_BASE_HOURS, params.BUDGET_PER_DAY, params.NO_DATA_TIMEOUT_HOURS) == (6, 3, 24)

def test_band_order_and_severity():
    assert Band.VERY_UNHEALTHY > Band.UNHEALTHY and Band.VERY_UNHEALTHY.is_severe and not Band.UNHEALTHY.is_severe
    assert Band.parse("usg") is Band.USG

def test_qa_eval_05_no_wall_clock_in_src():
    offenders = [p for p in Path("src/aqagent").rglob("*.py") if p.name != "clock.py"
                 and re.search(r"datetime\.(now|utcnow)\(|time\.time\(|date\.today\(", p.read_text())]
    assert offenders == []
```

- [ ] **Step 2:** `uv init --package --name aqagent --python 3.13` (or write `pyproject.toml` by hand with the deps and extras above, and `[tool.pytest.ini_options] pythonpath=["src"]`), then `uv sync --all-extras`. Run `uv run pytest tests/test_foundation.py -v`. Expected: FAIL (modules missing).
- [ ] **Step 3:** Implement `params.py`, `types.py`, `clock.py` and `tests/fixtures.py` per the Interfaces block.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: 3 passed.
- [ ] **Step 5:** Commit `chore: project skeleton, parameters, clock and shared types`.

---

### Task 2: AQI — NowCast and EPA bands

**Files:** Create `src/aqagent/understand/aqi.py`, `tests/test_aqi.py`

**Interfaces:**
- Produces: `band_for(pm25: float) -> Band` (truncate to 0.1 first); `nowcast(window: list[tuple[int, float]]) -> float | None`, where `window` holds `(hours_ago, value)` pairs for the last 12 h, clean values only; `aqi_value(pm25: float) -> int` (EPA linear interpolation over the 2024 breakpoints).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("c,band", [(9.0,"good"),(9.1,"moderate"),(35.4,"moderate"),(35.5,"usg"),(55.4,"usg"),
    (55.5,"unhealthy"),(125.4,"unhealthy"),(125.5,"very_unhealthy"),(225.4,"very_unhealthy"),(225.5,"hazardous")])
def test_qa_ing_10_band_boundaries(c, band): assert band_for(c) is Band.parse(band)

def test_qa_ing_11_nowcast_weighting_and_validity():
    assert nowcast([(2, 10.0), (5, 10.0)]) is None                    # only 1 of the 3 most recent hours is valid
    assert nowcast([(0, 10.0), (1, 10.0), (2, 10.0)]) == pytest.approx(10.0)
    w = [(0, 100.0)] + [(h, 10.0) for h in range(1, 12)]               # max-min/max = 0.9 -> w clamped to 0.5
    assert nowcast(w) == pytest.approx(sum(0.5**h * c for h, c in w) / sum(0.5**h for h, _ in w), abs=0.1)
    assert aqi_value(35.5) == 101 and aqi_value(9.0) == 50
```

- [ ] **Step 2:** Run `uv run pytest tests/test_aqi.py -v`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement. NowCast per S-B §2: `w = max(0.5, 1 - (max-min)/max)` (`w = 1` when `max == 0`), `sum(w**h * c) / sum(w**h)`, truncated to 0.1.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat: NowCast and EPA 2024 PM2.5 bands`.

---

### Task 3: Storage, readings with revisions, OpenAQ client and ingestion (S1)

**Files:** Create `src/aqagent/db.py`, `src/aqagent/repo.py`, `src/aqagent/sense/openaq.py`, `src/aqagent/sense/ingest.py`, `tests/test_ingest.py`

**Interfaces:**
- Produces:
  - `db.metadata` with the tables of S-A §5 (`stations, sensors, readings, ingestion_runs, users, user_rules, baselines, station_scores, episodes, decisions, notifications, feedback`) plus a `held_notices` table: `(id, user_id, decision_id, candidate JSON, held_at, released_decision_id NULL)`. Also `db.make_engine(url: str) -> Engine` and `db.create_all(engine)`.
  - `repo.upsert_readings(conn, rows: list[Reading], ingested_at: datetime, run_id: int) -> tuple[int, int]` (new, revised). It inserts a row only when `(sensor_id, period_end)` is new or the value changed.
  - `repo.readings_as_of(conn, sensor_id: int, start: datetime, end: datetime, as_of: datetime) -> list[Reading]` (latest version with `ingested_at <= as_of`, ascending).
  - `openaq.OpenAQClient(api_key: str, transport: httpx.BaseTransport | None = None)` with `.hours(sensor_id: int, dt_from: datetime, dt_to: datetime) -> list[Reading]` (pages through `limit=1000`; backs off on 429 using `x-ratelimit-reset`, max 3 tries; exposes `.last_ratelimit_remaining`). Raises `MissingAPIKey` at construction when the key is empty.
  - `ingest.run_ingestion(conn, client, clock, sensor_ids: list[int]) -> IngestReport` (`IngestReport.changed: dict[int, list[datetime]]` maps sensor id to the new or revised `period_end`s). Window = last 24 h, or a backfill of up to 90 days when the sensor's newest stored hour is older than 24 h. One `ingestion_runs` row per sensor.

- [ ] **Step 1: Write the failing tests**, using `httpx.MockTransport` serving OpenAQ-shaped JSON (`{"meta":{...},"results":[{"value":..,"period":{"datetimeFrom":{"utc":..},"datetimeTo":{"utc":..}},"coverage":{"percentCoverage":..}}]}`):
  - `test_qa_ing_01_trailing_window`: 5 sensors → exactly 5 `/sensors/{id}/hours` requests, each with `datetime_from == now - 24h`.
  - `test_qa_ing_02_idempotent`: ingest the same payload twice → second report `new == revised == 0`.
  - `test_qa_ing_03_revision_kept`: value 40 then 55 for one hour → 2 rows; `readings_as_of(as_of=before second run)` returns 40; as of now, 55.
  - `test_qa_ing_04_gaps_not_interpolated`: 3 absent hours → no rows for them.
  - `test_qa_ing_06_backfill`: empty DB → `datetime_from == now - 90d`; `kind == 'backfill'`.
  - `test_qa_ing_07_partial_failure`: one sensor returns 500 → its run `status == 'error'`, others `ok`; the next run fills its hours.
  - `test_qa_ing_08_rate_limit_backoff`: a 429 then a 200 → one retry after a sleep (inject `sleep` as a parameter and assert the call), `ratelimit_remaining` stored.
  - `test_qa_ing_09_half_hour_periods`: a period ending `05:30Z` is stored as `05:30Z`.
  - `test_qa_ing_12_missing_key`: `OpenAQClient("")` raises `MissingAPIKey`; with a key, `caplog` never contains it.
  - `test_qa_ing_13_run_row`: the run row has started/finished, counts, `newest_period_end`, status.
  - `test_review_sensor_404_is_partial`: a 404 for one sensor → its run is `error`, no exception escapes, other sensors ingested.
- [ ] **Step 2:** Run `uv run pytest tests/test_ingest.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `db.py`, `repo.py` (the functions above, plus small getters later tasks add as needed), `openaq.py` and `ingest.py`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat: storage with reading revisions and OpenAQ ingestion`.

---

### Task 4: S2 VALIDATE

**Files:** Create `src/aqagent/sense/validate.py`, `tests/test_validate.py`

**Interfaces:**
- Produces: `validate(readings: list[Reading], provisional_last: bool = True) -> list[CheckedReading]`, where `CheckedReading(reading: Reading, excluded: ReasonCode | None, provisional: bool)`, ascending by time. Plus `gap_breaks(readings) -> set[datetime]`: the `period_end`s that follow a gap of more than `GAP_RESET_HOURS`.

- [ ] **Step 1: Write the failing tests:**
  - `test_qa_dq_01_invalid`: −1 and 1200 → `DQ_INVALID`.
  - `test_qa_dq_02_low_coverage`: coverage 60 → `DQ_LOW_COVERAGE`.
  - `test_qa_dq_03_stuck`: 6 identical values → all 6 `DQ_STUCK`.
  - `test_qa_dq_04_glitch_mumbai`: `[75, 980, 90]` → the middle is `DQ_SUSPECT`.
  - `test_qa_dq_05_provisional_last`: `[30, 200]` → the last is `provisional=True`, `excluded=None`; after appending 30 → `DQ_SUSPECT`.
  - `test_qa_dq_08_gap_breaks`: a 4 h gap → the hour after it is in `gap_breaks`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement with the S-C §2 rules and `params`.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: S2 data-quality checks`.

---

### Task 5: U1 LEARN — hour-of-day baseline

**Files:** Create `src/aqagent/understand/baseline.py`, `tests/test_baseline.py`

**Interfaces:**
- Consumes: `CheckedReading` (Task 4), `band_for` (Task 2).
- Produces: `Baseline(m: dict[int, float], s: dict[int, float], m_all: float, s_all: float, typical_band: Band, n_hours: int, trained_through: datetime)`; `fit_baseline(clean: list[CheckedReading], tz: ZoneInfo, as_of: datetime) -> Baseline | None` (None when < `MIN_HISTORY_HOURS` clean hours in the 14 days before `as_of`); `Baseline.expected(hour_local: int) -> tuple[float, float]` returns `(m_h, s_h)` with shrinkage and the floor applied.

- [ ] **Step 1: Write the failing tests:**
  - `test_qa_det_01_hour_of_day_shrink_floor`: a synthetic 14-day series with `log1p` medians known per hour → `m[h]` matches `statistics.median`. For an hour with 3 samples, `expected(h)` is the `3/7` blend toward all-hours. A flat series gives `s == 0.15`.
  - `test_qa_dq_07_no_baseline`: 71 clean hours → `None`.
  - `test_qa_det_02_typical_band` (sample data): Delhi (4712609) → `Band.USG`; Helsinki (4588) → `Band.GOOD`. Load with a new helper in `tests/fixtures.py`: `sample_readings(location_id: int) -> list[Reading]`, which reads `data/samples/openaq_pm25_hourly_90d.csv`.
  - `test_review_dst_hour_buckets`: Helsinki readings across the 2026-10-25 fall-back → no exception, and the repeated local 03:00 hour lands in bucket 3 both times.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement per S-C §3 (`y = log1p(v)`, `s = 1.4826·MAD`, weight `n/7`, all-hours fallback below 2 samples, floor `MAD_FLOOR`).
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: U1 hour-of-day robust baseline`.

---

### Task 6: U2 SCORE — shared station scores

**Files:** Create `src/aqagent/understand/score.py`, `tests/test_score.py`; Modify `src/aqagent/types.py` (add `StationScore`), `src/aqagent/repo.py` (add `save_scores`, `scores_window`)

**Interfaces:**
- Consumes: Tasks 2, 4, 5.
- Produces: `StationScore(sensor_id, period_end, z, ewma, cusum, slope_6h, nowcast, band, typical_band, excluded: ReasonCode|None, gap_break: bool, evidence: dict)` (frozen dataclass in `types.py`); `score_hours(readings_known: list[Reading], tz, hours: list[datetime], as_of: datetime) -> list[StationScore]`. It recomputes each hour from the 14-day/72-hour windows ending at that hour. Excluded or unscorable hours carry `excluded` and `z=None`. Also `repo.save_scores(conn, scores, evaluated_at)` and `repo.scores_window(conn, sensor_id, end: datetime, hours: int = 72) -> list[StationScore]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_score_values`: a known 14-day baseline plus a final hour → `z` equals `(log1p(v)-m_h)/s_h`. `ewma` follows λ 0.3 from the window start. `cusum` follows `max(0, c+z-0.5)` with the default-bar reset at `ELEVATED_H`. `slope_6h` is the Theil–Sen median of pairwise slopes of `log1p`.
  - `test_qa_det_11_deterministic`: scoring the same inputs twice → identical lists.
  - `test_score_gap_resets_ewma`: a gap > 3 h → `ewma` re-seeds at the first hour after the gap.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Theil–Sen over the clean hours in the last 6 h (≥ 3 points, else `None`).
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: U2 shared station scores`.

---

### Task 7: User rules and S3 RESOLVE stub

**Files:** Create `src/aqagent/decide/rules.py`, `src/aqagent/sense/resolve.py`, `config/users.yaml`, `tests/test_rules.py`; Modify `src/aqagent/repo.py` (add `save_rules`, `current_rules`)

**Interfaces:**
- Produces:
  - `Rules` (pydantic, `extra="forbid"`): fields and defaults exactly as in S-C §8 (`location.station_id`, `pollutants=["pm25"]`, `sensitivity="default"`, `relevance_floor=Band.MODERATE`, `alert_band` defaulting to `very_unhealthy`, or `unhealthy` when `sensitivity == "high"`, `quiet_hours(start="22:00", end="07:00", breakthrough_band=very_unhealthy)`, `check_in.cron: str | None = None`, `pace.base_gap_hours=6`, `budget.max_per_day=3`). Cron is validated with `CronTrigger.from_crontab`. Plus `Rules.k -> float`.
  - `load_rules(raw: dict | None, previous: Rules | None) -> tuple[Rules, ReasonCode | None]` (returns the previous version and `RULES_INVALID` on error, defaults when `raw is None`).
  - `resolve.station_for(rules: Rules) -> int` (the stub).
  - `config/users.yaml` with the six demo users. Arjun (Delhi, default, runs 06:30, check-in `30 6 * * *`). Meera (Delhi, high sensitivity, asthma). Priya (Bengaluru, default, runs 06:00, check-in `0 6 * * *`). Omar (Dubai, low). Maya (Los Angeles, default, commuter). Aino (Helsinki, high, asthma).
- [ ] **Step 1: Write the failing tests:**
  - `test_qa_rule_01_defaults`: `load_rules(None, None)` → the S-C §8 defaults; `k == 1.0`.
  - `test_qa_rule_02_invalid_falls_back`: an unknown field, a bad band and a bad cron → each returns the previous rules plus `RULES_INVALID`.
  - `test_high_sensitivity_alert_band_default`: `sensitivity="high"` → `alert_band is Band.UNHEALTHY`.
  - `test_qa_rule_11_resolve`: returns `rules.location.station_id`.
  - `test_qa_rule_03_versions` (repo): saving twice gives versions 1 and 2, and `current_rules` returns 2.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: user rules with defaults and validation; S3 resolve stub`.

---

### Task 8: D1 TRIGGER

**Files:** Create `src/aqagent/decide/trigger.py`, `tests/test_trigger.py`

**Interfaces:**
- Consumes: `StationScore` window (Task 6), `Rules.k`, `Rules.alert_band`.
- Produces: `TriggerResult(label: EventKind | None, fired: frozenset[EventKind], calm: bool, near_misses: tuple[str, ...], bars: dict[str, float])`; `triggers(window: list[StationScore], k: float, alert_band: Band) -> list[TriggerResult]`, one per hour in the window, where the last is the evaluated hour. It recomputes the user's own CUSUM over the window with bar `ELEVATED_H*k`, resetting after it fires.

- [ ] **Step 1: Write the failing tests** (build windows with a helper that sets `z/ewma/slope/band` directly):
  - `test_qa_det_03_spike_two_of_three`: z `[0, 4, 0]` → no spike; `[4, 0, 4]` → spike.
  - `test_qa_det_04_climb_three_hours_and_rising`: EWMA above 1.26 for 2 h → no climb; for 3 h with slope 0.02 → climb.
  - `test_qa_det_15_flat_plateau_is_elevated_not_climb`: EWMA above 1.26 for 6 h, slope 0 → climb never fires, and elevated fires once the CUSUM passes 8.
  - `test_qa_det_05_elevated_slow_build`: z = 1.5 for 12 h → no spike or climb; elevated fires at the hour the cumulative `z-0.5` exceeds 8, then resets.
  - `test_qa_det_06_elevated_needs_ewma`: CUSUM > 8 while EWMA < 0.5 → not fired.
  - `test_qa_det_08_floor_edge_triggered`: bands below → at/above `alert_band` for 2 of 3 h → floor fires once; staying there 48 h → no refire.
  - `test_qa_det_09_near_miss`: z = 3.0 twice → `near_misses` contains `"spike"`, `fired` is empty.
  - `test_qa_det_14_one_label_by_precedence`: spike, climb and elevated all fire → `label is EventKind.spike`.
  - `test_qa_sens_01_high_sensitivity`: z = 3.0 in 2 of 3 h → fires at k 0.75, not at k 1.0.
  - `test_qa_sens_02_low_sensitivity`: z = 4.0 in 2 of 3 h → fires at 1.0, not at 1.25.
  - `test_calm_hour`: EWMA 0.4, nothing fired, band ≤ typical → `calm is True`; band above typical → `False`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement per S-C §5.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: D1 triggers: spike, climb, elevated, floor, calm`.

---

### Task 9: D2 EPISODE

**Files:** Create `src/aqagent/decide/episode.py`, `tests/test_episode.py`

**Interfaces:**
- Consumes: `TriggerResult` (Task 8), `StationScore` (band).
- Produces: `EpisodeState` (frozen dataclass mirroring the `episodes` row: `id|None, state ∈ {"ACTIVE","RECOVERING","CLOSED"}, opened_at, closed_at, close_reason, kinds: frozenset, peak_value, peak_band, last_notified_at, last_notified_band, last_notified_kind, notifications_sent`); `step_episode(prev: EpisodeState | None, last_closed: EpisodeState | None, trig: TriggerResult, score: StationScore, calm_run: int, relevance_floor: Band, at: datetime) -> tuple[EpisodeState | None, CandidateKind | None, ReasonCode | None]`; `timeout_episode(prev: EpisodeState, newest_reading_at: datetime, at: datetime) -> EpisodeState | None` (closes it with `close_reason="no_data_timeout"` after 24 h).

- [ ] **Step 1: Write the failing tests:**
  - `test_opens_when_event_and_moderate`: no episode + a climb at USG → ACTIVE, candidate `opened`.
  - `test_no_open_below_relevance`: a climb at Good → no episode, `NO_TRIGGER`.
  - `test_escalation_candidate`: ACTIVE, last notified USG, now Unhealthy → candidate `escalated`. Same band → `EPISODE_CONTINUES`.
  - `test_qa_det_07_clearing_four_calm_hours`: `calm_run` 3 → RECOVERING with no candidate; 4 → CLOSED and candidate `cleared`.
  - `test_qa_dedup_04_flap_guard`: closed 4 h ago + a new event → the same `id` reopens ACTIVE, and the candidate is `None` unless the band is above `last_notified_band`.
  - `test_qa_dq_09_no_data_timeout`: ACTIVE, newest reading 23 h old → unchanged; 24 h → CLOSED, `close_reason == "no_data_timeout"`, and no candidate is ever produced.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement per S-C §6.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: D2 episode lifecycle with flap guard and no-data timeout`.

---

### Task 10: D3–D8 restraint and the per-user pipeline

**Files:** Create `src/aqagent/decide/restraint.py`, `src/aqagent/decide/pipeline.py`, `tests/test_restraint.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 7–9.
- Produces:
  - `restraint.worth_it(candidate, episode, score) -> TraceStep`; `pace(candidate, episode, at, base_gap_h) -> TraceStep` (required gap = `base * 2**(notices_in_episode-1)` for the 2nd and later notices; severe bypasses); `arbitrate(candidates: list[Candidate]) -> tuple[Candidate, list[Candidate]]` (priority escalated > opened > cleared > check_in); `respond(candidate) -> TraceStep` (always `notify`); `budget(sent_nonsevere_today: int, max_per_day: int, severe: bool) -> TraceStep`; `timing(at_local: datetime, rules, band: Band, is_check_in: bool) -> TraceStep`.
  - `Candidate(kind: CandidateKind, band: Band, episode_id: int | None, event_kind: EventKind | None, severe: bool)`.
  - `pipeline.UserHourContext(user_id, rules, rules_version, tz, score: StationScore, window: list[StationScore], episode: EpisodeState|None, last_closed: EpisodeState|None, sent_today_nonsevere: int, last_sent_at: datetime|None, at: datetime)`.
  - `pipeline.Evaluation(outcome: Outcome, reason_code: ReasonCode, trace: list[TraceStep], episode_after: EpisodeState|None, candidate: Candidate|None, hold: bool)`.
  - `pipeline.evaluate_hour(ctx: UserHourContext) -> Evaluation`, running the S-C §7.2 order and appending a `TraceStep` for every layer reached, stubs included.
  - `pipeline.evaluate_check_in(ctx: UserClockContext, held: list[Candidate]) -> Evaluation` and `pipeline.evaluate_release(ctx: UserClockContext, held: list[Candidate]) -> Evaluation`, where `UserClockContext` has the same fields as `UserHourContext` minus `score`, plus `newest_reading_at`.
- [ ] **Step 1: Write the failing tests** (`test_restraint.py` for single layers, `test_pipeline.py` end to end over synthetic windows):
  - `test_qa_sens_04_relevance_floor`: Helsinki-like baseline, 3→5 (Good) → `suppressed · BELOW_RELEVANCE`; 4→15 (Moderate) → `sent`.
  - `test_qa_dedup_01_six_bad_hours_one_notice`: 6 consecutive Unhealthy hours → exactly 1 `sent`; the rest `DEDUP_SAME_BAND` or `EPISODE_CONTINUES`.
  - `test_qa_dedup_02_escalation_after_pace`: told at USG; Unhealthy 7 h later → `SENT_ESCALATED`.
  - `test_qa_dedup_03_same_band_quiet`: `DEDUP_SAME_BAND`.
  - `test_qa_dedup_05_pace_doubles`: required gaps of 6, then 12, then 24 h within one episode; 6 again after close.
  - `test_qa_dedup_06_budget`: a 4th non-severe notice in a local day → `DAILY_BUDGET`.
  - `test_qa_dedup_11_budget_separate_from_pace`: a 4th candidate from a second episode, pace passes → the D4 step passed, and D7 fails with `DAILY_BUDGET`.
  - `test_qa_dedup_07_severe_bypass`: pace and budget exhausted + Very Unhealthy escalation → `SENT_SEVERE_BYPASS`.
  - `test_qa_dedup_08_clear_worth_saying`: a 5 h Moderate episode → `RECOVERY_NOT_WORTH_SAYING`; a 14 h one → `SENT_CLEARED`.
  - `test_qa_dedup_09_arbitration`: escalated + check-in candidates → the escalated one wins; the other is `ARBITRATED_OUT`.
  - `test_qa_rule_04_quiet_hours_hold`: Moderate opened at 03:00 local → `held · QUIET_HOURS_HELD`.
  - `test_qa_rule_05_breakthrough`: Very Unhealthy at 03:00 → `sent · SENT_SEVERE_BYPASS`.
  - `test_qa_rule_08_check_in_speaks_only_when_worse`: a bad night → `SENT_CHECK_IN`; an ordinary night → `CHECKIN_QUIET`.
  - `test_qa_rule_09_check_in_gap`: sent 4 h before → `CHECKIN_QUIET`.
  - `test_qa_rule_14_check_in_wins_and_absorbs`: 06:30 inside quiet hours with one held candidate → `SENT_CHECK_IN`, and the evaluation lists the held candidate as absorbed.
  - `test_qa_rule_06_release_collapses`: 3 held → one `sent` evaluation at quiet end.
  - `test_qa_rule_07_held_expired`: the episode closed overnight and was never told → `HELD_EXPIRED`, nothing sent.
  - `test_qa_sens_03_normal_for_delhi`: a USG week then a crossing into Very Unhealthy → no repeated notices during the week; one at the crossing.
  - `test_qa_rule_13_trace_order`: the trace layers are a prefix of `["S2/U2","D1","D2","D3","D4","D5","D6","D7","D8","A"]`, and D5–D7 entries are present when reached.
  - `test_qa_rule_10_local_time_dst`: quiet hours and the check-in for Helsinki and Los Angeles across their 2026 DST changes land on the right local wall-clock times.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement restraint layers and pipeline per S-C §7.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: D3-D8 restraint layers and the per-user pipeline`.

---

### Task 11: A1 COMPOSE and A2 DELIVER stub

**Files:** Create `src/aqagent/act/facts.py`, `src/aqagent/act/compose.py`, `src/aqagent/act/deliver.py`, `tests/test_compose.py`

**Interfaces:**
- Consumes: `Evaluation`, `Candidate`, episode, scores window, user persona.
- Produces: `facts.build_insight(...) -> dict` (the S-C §9 shape, including `history_facts` and `action_candidates` from a fixed `ACTION_CATALOGUE: dict[tuple[CandidateKind, Band], list[str]]` filtered by persona habit and local hour); `compose.compose(insight: dict, llm: Callable[[str], str] | None, timeout_s: float = LLM_TIMEOUT_S) -> ComposedMessage(body: str, next_action: str, generator: str)`; `compose.validate_message(body, insight) -> list[str]` (errors); `compose.template(insight) -> ComposedMessage`; `compose.anthropic_llm(model: str) -> Callable[[str], str] | None` (None when `ANTHROPIC_API_KEY` is unset); `deliver.deliver(conn, decision_id, user_id, msg, insight, deliver_after, at) -> int` (writes `notifications`, returns its id).
- Implementation note: load the `claude-api` skill before writing `anthropic_llm`. The prompt asks for one or two sentences using only the given facts and exactly one of `action_candidates`.

- [ ] **Step 1: Write the failing tests:**
  - `test_qa_msg_01_shape`: a template message for every candidate kind is ≤ 220 chars, isn't JSON, and doesn't match `r"^\s*AQI is now \d+\.?\s*$"`.
  - `test_qa_msg_02_one_action`: exactly one string from `action_candidates` appears in `body`; `next_action` equals it.
  - `test_qa_msg_03_past_context`: for spike, climb, elevated and cleared, `history_facts` is non-empty, and at least one appears (case-insensitive) in the body.
  - `test_qa_msg_04_no_invented_numbers`: an LLM stub returning "AQI hit 999" → `validate_message` reports it, and `compose` falls back to `generator == "template"`.
  - `test_qa_msg_05_no_llm`: `llm=None` → a template, valid.
  - `test_qa_msg_06_bad_llm_output`: 400 chars, or no action → fallback.
  - `test_qa_msg_07_persona_action`: a runner at 06:00 with a climb → the action mentions the run.
  - `test_qa_msg_08_released_mentions_night`: a released kind with `absorbed_held` → the body mentions the overnight period and the current state.
  - `test_review_llm_timeout_falls_back`: an LLM stub sleeping 30 s with `timeout_s=0.2` → returns a template within 1 s.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Run the LLM call in a `concurrent.futures` thread with a timeout. Number check: every number and date token in the body must appear in the JSON-dumped insight.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat: A1 compose with validator and template fallback; A2 deliver stub`.

---

### Task 12: Runner — data run and clock tick, with persistence

**Files:** Create `src/aqagent/runner.py`, `tests/test_runner.py`; Modify `src/aqagent/repo.py` (episode, decision, held and notification read/write helpers)

**Interfaces:**
- Consumes: Tasks 3–11.
- Produces: `runner.data_run(conn, changed: dict[int, list[datetime]], clock, llm) -> RunSummary`. For each changed sensor, it scores the changed hours as known now and saves the scores. For each user on that sensor, it evaluates every changed hour newer than the user's last evaluated hour, in order (D2 state persisted after each). Changed hours at or before that high-water mark get `no_event · LATE_HOUR_SCORED`. `runner.clock_tick(conn, clock, llm, event: Literal["hourly","check_in","quiet_end"], user_ids: list[str] | None) -> RunSummary`: NO_DATA when the newest reading is more than 3 h old (plus the 24 h timeout), check-ins, releases. Both write `decisions.trigger`. `RunSummary(decisions: int, sent: int, held: int)`.

- [ ] **Step 1: Write the failing tests** (in-memory SQLite, seeded stations, users and synthetic readings):
  - `test_qa_ing_05_late_hour_evaluated`: an outage then 5 hours arriving together → 5 decisions per user, in order (`test_qa_det_13_outage_evaluates_every_hour` is the same scenario).
  - `test_review_late_hour_does_not_rewind_episode`: H+1..H+3 evaluated, then H arrives → H is scored, the decision is `LATE_HOUR_SCORED`, the episode row is unchanged, no notice.
  - `test_qa_clk_01_no_data_decisions`: no readings for 4 h → each hourly tick writes `no_event · NO_DATA` with `trigger == "clock"`.
  - `test_qa_clk_02_release_without_new_data`: held at 01:00, no data after 05:00, the 07:00 quiet_end tick → one sent notice, `trigger == "clock"`.
  - `test_qa_dq_06_no_data_freezes`: an open episode + 5 h silence → no state change and no notice; when data returns, the gap hours are evaluated in order.
  - `test_qa_dedup_10_restart_safe`: run, rebuild the runner from the same DB, run the next hour → no duplicate `opened`; the pace gap is honoured.
  - `test_qa_obs_01_row_per_user_hour`: 24 h × 5 users of clean data → 120 decision rows.
  - `test_qa_obs_02_suppressed_complete`: a suppressed and a held decision each have `reason_code`, a `reason` sentence, a non-empty `trace` and `score_ids`.
  - `test_qa_rule_12_pollutant_filter`: a user with `pollutants=["pm25"]` and a station that also has a (synthetic) pm10 sensor → only pm25 `station_scores` feed that user's decisions.
  - `test_qa_sens_05_scores_independent_of_users`: score with default users only, then with a high-sensitivity user added → identical `station_scores` rows.
  - `test_qa_det_12_live_equals_replay`: hour-by-hour live runs vs one replay over the same as-known data → the same outcome and reason code per user-hour (uses `replay.harness.replay` from Task 13; mark it `xfail` until Task 13 lands, then remove the mark).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Each decision gets a one-sentence `reason` generated from its terminal trace step, e.g. "Held: quiet hours until 07:00".
- [ ] **Step 4:** Run them. Expected: PASS (`test_qa_det_12` xfail).
- [ ] **Step 5:** Commit `feat: runner with data run, clock tick and persistence`.

---

### Task 13: REPLAY — as-known loader, harness, labels and report

**Files:** Create `src/aqagent/replay/load.py`, `src/aqagent/replay/harness.py`, `src/aqagent/replay/labels.py`, `data/labels.yaml`, `tests/test_replay.py`

**Interfaces:**
- Consumes: the runner (Task 12); `data/samples/openaq_pm25_hourly_90d.csv`, `data/samples/stations.json`.
- Produces: `load.load_sample(conn, csv_path, stations_path, lag_hours: float = 1.5) -> int`, which sets `ingested_at = period_end + lag`; `harness.replay(conn, start, end, run_id: str, llm=None) -> ReplaySummary`, which steps a `FixedClock` through every hourly `:20` tick plus each user's check-in and quiet-end times (from `CronTrigger`), calling the runner with readings known by then, and tags decisions with `replay_run`; `labels.reference_moments(readings, tz) -> list[Moment(start, end, kind)]` (ruptures PELT `l2` on `log1p`, penalty `3*log(n)`, then the S-C §12 filters) merged with `data/labels.yaml` (Helsinki 2026-08-24 05:00–09:00 positive; Mumbai DQ_SUSPECT hours negative); `harness.report(conn, run_id, moments) -> dict` with per station and persona: `caught, missed, false_alarms, notices_per_week, median_time_to_notify_h, near_misses_by_missed`.

- [ ] **Step 1: Write the failing tests:**
  - `test_qa_eval_01_runs_without_key`: `monkeypatch.delenv("OPENAQ_API_KEY")`; load the sample and replay 7 days → completes; the report has 5 stations.
  - `test_qa_eval_02_report_fields`: report keys as above, for every station × persona.
  - `test_qa_eval_03_glitch_fixture_silent` and `test_qa_dq_04_glitch_mumbai_replay`: a replay over Mumbai with a test user → no sent notice whose triggering hour is `DQ_SUSPECT`.
  - `test_qa_eval_04_helsinki_smoke_caught`: Aino → a sent or held decision between 2026-08-24 05:00 and 11:00 UTC.
  - `test_qa_eval_06_volume_guard`: default persona over the full 90 days → `notices_per_week <= 4` for every tracked station.
  - `test_qa_eval_07_labels_independent`: `reference_moments` imports nothing from `aqagent.decide`. Check with `ast` over `labels.py`.
  - `test_qa_obs_06_replay_tagged`: every replay decision has `replay_run == run_id`; live queries (`replay_run IS NULL`) see none.
  - `test_qa_det_10_same_value_differs_by_city`: inject 15 µg/m³ into Helsinki and into Delhi → a trigger in Helsinki, none in Delhi.
  - Remove the `xfail` from `test_qa_det_12_live_equals_replay`.
- [ ] **Step 2:** Run `uv run pytest tests/test_replay.py tests/test_runner.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS. Record the actual `notices_per_week` per station in the commit message. They replace S-C §11's table during the post-build propagation.
- [ ] **Step 5:** Commit `feat: replay harness, reference labels and report`.

---

### Task 14: API, feedback, CLI and scheduler

**Files:** Create `src/aqagent/api.py`, `src/aqagent/learn/feedback.py`, `src/aqagent/cli.py`, `tests/test_api.py`, `tests/test_scheduler.py`; Modify `pyproject.toml` (`[project.scripts] aqagent = "aqagent.cli:main"`)

**Interfaces:**
- Produces:
  - FastAPI `app` with routes: `GET /health` (DB ok, newest reading age per sensor from `ingestion_runs`); `GET /users`; `GET /users/{id}/feed` (delivered notifications, newest first); `GET /decisions?user_id&start&end&outcome&replay_run`; `GET /notifications/{id}/explain` (decision, trace, the score rows behind `score_ids`, readings as of `evaluated_at`, baseline, and rules version); `POST /notifications/{id}/feedback {action}` (404 for unknown ids); `GET /users/{id}/export` (CSV of time, kind, body, next_action, decision_id).
  - `feedback.record(conn, notification_id, user_id, action, at)`.
  - CLI: `aqagent init-db`, `aqagent seed` (stations from `data/samples/stations.json` for the 5 tracked cities, users and rules from `config/users.yaml`), `aqagent backfill`, `aqagent tick` (one ingestion + data run + hourly clock tick), `aqagent run` (APScheduler: an hourly `:20` UTC job plus per-user check-in and quiet-end jobs; `max_instances=1`, `coalesce=True`), `aqagent serve` (uvicorn), `aqagent replay --days N --run-id X`, `aqagent report --run-id X`, `aqagent export --user ID --run-id X`.
- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient` over a replayed in-memory DB):
  - `test_qa_obs_03_explain`: for a sent notification → the response has `trace`, `scores`, `readings`, `baseline` and `rules_version`, and the readings are as of `evaluated_at`.
  - `test_qa_obs_04_missing_nudge_query`: `/decisions?user_id=aino&start..end` returns the suppressed rows with `reason_code` and `reason`.
  - `test_qa_obs_05_export`: the CSV header and a row per notice.
  - `test_qa_fb_01_feedback_recorded`: POST `acted` → a row exists; `user_rules` is unchanged.
  - `test_qa_fb_02_unknown_404`.
  - `test_health_empty_db`: a fresh DB → 200 with empty lists, not 500.
  - `test_review_scheduler_no_overlap`: the scheduler built by `cli.build_scheduler()` has `max_instances == 1` and `coalesce is True` on the hourly job; two concurrent `tick()` calls on the same DB produce no duplicate notifications (guarded by a `run_lock` row or a SQLite/Postgres advisory lock).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v` (the whole suite). Expected: all pass.
- [ ] **Step 5:** Commit `feat: API, feedback, CLI and scheduler`.

---

### Task 15: Live run, hosting and README run instructions

**Files:** Modify `README.md` (a "Run it" section and the status checklist), `.env.example` (`DATABASE_URL`, `ANTHROPIC_API_KEY`, `AQAGENT_LLM_MODEL`); Create the deployment config for the chosen host

- [ ] **Step 1: Decision checkpoint (ask the user).** Choose the host for the always-on process plus a managed Postgres. Present two options with cost and the cron granularity each supports for `:20` hourly and 06:30-style check-ins. Load the `vercel:marketplace` skill before naming a database provider if Vercel is one of them. Don't proceed without an answer.
- [ ] **Step 2:** Run locally against live OpenAQ: `uv run aqagent init-db && uv run aqagent seed && uv run aqagent backfill && uv run aqagent tick`. Expected: 5 `ingestion_runs` rows `ok` (or `error` only for a sensor that's actually down) and a decision row per user. `uv run aqagent serve`, then `curl localhost:8000/health` → 200.
- [ ] **Step 3:** Deploy, set secrets on the host (never in git), and confirm the first hourly run.
- [ ] **Step 4: QA-NFR-01 (manual):** after 24 h, there are 24 `ingestion_runs` per sensor and freshness under 3 h for active sensors. **QA-NFR-02 (manual):** `git log -p | grep -c OPENAQ_API_KEY=` shows only the empty `.env.example` line, and the host logs contain no key.
- [ ] **Step 5: QA-DEL-01:** add "Run it" to the README (the commands from Step 2 plus `aqagent replay`), keeping the attribution line. Commit `docs: run instructions and deployment`.

---

### Task 16: Submission artifacts

**Files:** Create `docs/architecture-note.md`, `docs/notification-history/` (exported CSVs), `docs/transcripts/` (exported Claude Code session transcripts)

- [ ] **Step 1: QA-DEL-02:** write `docs/architecture-note.md`, one to two pages, human-first. It covers the layer model (linking the explainer), the five most important decisions with trade-offs, the calibration results from Task 13, known limitations (low-cost sensor bias, Bengaluru labelled "indoor", PM2.5 only) and next steps toward full scope.
- [ ] **Step 2: QA-DEL-04:** `uv run aqagent replay --days 90 --run-id final` then `uv run aqagent export --user <id> --run-id final` for every user → `docs/notification-history/<user>.csv`, plus the live feed export if it's deployed.
- [ ] **Step 3: QA-DEL-03:** export this project's Claude Code session transcripts into `docs/transcripts/` (ask the user for the export method available on their surface).
- [ ] **Step 4: QA-DEL-05 (user):** record the demo video, covering the explainer diagram, a live or replay feed, one `explain` trace for a sent notice and one for a suppressed one, and the harness report. Add the link to the README.
- [ ] **Step 5:** Commit `docs: architecture note, notification history and transcripts`.

---

### Task 17 (optional, first to cut): Concept demo UI

**Files:** Create `web/` (Next.js App Router, deployed to Vercel)

- [ ] **Step 1: QA-DEMO-01:** three read-only pages backed by the API: users' feeds, the decision log with plain-sentence traces, and the harness report. No auth (out of scope).
- [ ] **Step 2:** Deploy with the `vercel:deploy` skill. Add the URL to the README. Commit `feat: concept demo UI`.

---

## Self-review notes

- **Coverage:** every QA.csv row maps to a test above, or to a manual step in Tasks 15–17. Exceptions: QA-ING-10/11 and QA-DQ-* are unit tests in Tasks 2 and 4. QA-MSG-09 (human review of 20 messages) runs as part of Task 16 Step 1, from the final replay export. QA-DEL-06 is satisfied by S-C being complete (already true).
- **After the build:** propagate explainer-first: (1) the three spec additions above, (2) the measured calibration numbers into S-C §11, (3) the QA.csv `status` column from the test results.
