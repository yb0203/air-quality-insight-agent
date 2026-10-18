# S-A — OpenAQ API and data schema

Status: approved · updated 2026-10-18 from the closed [explainer](../explainer.md) · Layers S1–S3, U1–U2, RECORD, REPLAY · Implements: FR-ING, FR-SENS-1, FR-EVAL-4/5, FR-OBS-1, NFR-2/3/4 in [requirements.md](../requirements.md)

Everything below was verified against the live OpenAQ v3 API on 2026-10-18 (about 65 calls). The probe scripts aren't part of the repo; their output is summarised here and the raw sample lives in `data/samples/`.

---

## 1. OpenAQ v3: what matters for us

| Topic | Finding |
|---|---|
| Base URL | `https://api.openaq.org/v3` |
| Auth | Every call, including reads, needs `X-API-Key` (401 otherwise). Free key from explore.openaq.org. Read from `OPENAQ_API_KEY`. |
| Rate limits | 60 req/min, 2,000 req/hour per key. Headers: `x-ratelimit-limit/-used/-remaining/-reset`. 429 on excess; repeated abuse can get the key banned. |
| Data model | **Location** (a station: id, name, timezone, coordinates, provider, `isMonitor`, `instruments`, `licenses`, `datetimeLast`) → **Sensor** (one per pollutant: id, `parameter{id,name,units}`) → time series. |
| Hourly series | `GET /sensors/{id}/hours?datetime_from&datetime_to&limit(≤1000)&page`. Each row: `value` (hour mean), `period{datetimeFrom,datetimeTo}` (UTC and local), `coverage{expectedCount, observedCount, percentComplete, percentCoverage}`, `summary{min,q02,q25,median,q75,q98,max,avg,sd}`, `flagInfo`. Docs prefer `hours` over `measurements/hourly`. |
| Discovery | `GET /locations?coordinates=lat,lon&radius≤25000&parameters_id=2&limit=100`. |
| Latest | `GET /locations/{id}/latest` → `{datetime, value, sensorsId, locationsId, coordinates}`. Useful for health checks, not for history. |
| Flags | `GET /locations/{id}/flags` exists, but returned **nothing** for Mumbai over 90 days despite obvious ~980 µg/m³ glitches. **Data quality is entirely our job.** |
| Parameter ids | pm25 = 2 (µg/m³), pm10 = 1, no2 = 15, o3 = 32, so2 = 101, co = 102. |
| Latency | Newest hour is typically **0.5–2.5 h** behind real time. |
| Period alignment | Hour periods are aligned to the station's local clock, so India (UTC+5:30) periods end at `:30 UTC`. **Never assume `:00` UTC.** The reading's timestamp is `period.datetimeTo`. |
| Missing hours | Simply absent (no null rows). Gaps must be inferred from timestamps. |
| Bad values | Zeros/negatives occur on some sensors (Sydney low-cost sensors: about a third of hours ≤ 0). Isolated 1-hour spikes of 10–50× baseline occur (Mumbai). Some low-cost sensors are plainly miscalibrated or indoor (Singapore AirGradient units reading 100–250 in a city that's usually about 15). |

---

## 2. City and station selection

Probed 10 candidate cities (Delhi, Bengaluru, Mumbai, Dubai, Los Angeles, London, Zurich, Helsinki, Sydney, Singapore), then pulled 90 days of hourly PM2.5 for the shortlist.

Selection criteria: one primary station per distinct city; outdoor instrument; ≥ 95% hourly coverage over 90 days; fresh (< 6 h); and, across the set, a wide spread of baselines from very clean to naturally dusty.

| City | Station (OpenAQ location id → pm25 sensor id) | Provider / instrument | 90-day coverage | Median PM2.5 (µg/m³) | p95 | Daily pattern (local) | Role in the demo |
|---|---|---|---|---|---|---|---|
| **Helsinki** | Mannerheimintie (4588 → 11382) | EEA reference monitor | 98%, longest gap 10 h | 4.2 | 10.6 | flat (3.8–4.6) | Very clean city. A small absolute rise is "unusual" here (FR-SENS). Had a smoke-like episode on 24 Aug (≈ 27 µg/m³ for 4 h, ~6× baseline). |
| **Los Angeles** | Los Angeles – N. Main (7936 → 25196) | AirNow regulatory monitor, multi-pollutant | 98% | 10.0 | 19.2 | noon peak 13.2 | Clean-to-moderate city with occasional sharp jumps (3.9 → 29.9 in 1 h on 9 Oct). |
| **Bengaluru** | Koramangala (6206921 → 15203555) | AirGradient Open Air O-1PST (low-cost) | 99% | 20.7 | 51.9 | 09:00 peak 28.5, 17:00 low 13.7 | Moderate city, home of Orange Invest (next to HSR Layout). ⚠ See caveat below. |
| **Dubai** | Business Bay (6096447 → 14384841) | AirGradient Open Air O-1PST | 100% | 41.0 | 90.2 | midnight peak | **Naturally dusty** region: high baseline from desert dust, so a high-ish absolute value is normal there. |
| **Delhi** | Air Check (4712609 → 15289075) | AirGradient Open Air O-1PST | 100% | 45.9 | 98.7 | midnight peak 52.7 | Heavily polluted and **entering its seasonal pollution build-up now** (October), so live sustained-trend events are likely during the demo. |

Fixtures (kept in the sample, **not** tracked live):
- **Mumbai AirNow (8039)**: 56% coverage, a 147 h gap, and repeated one-hour spikes to 784–982 µg/m³ with no OpenAQ flag. This is the false-positive/glitch test case for FR-DET-5.
- **Delhi AirNow reference (8118)**: 77% coverage, a 356 h gap. Useful as a gap/no-data test case and a cross-check against the low-cost Delhi sensor.

Caveats, recorded honestly:
- **Bengaluru's only live sensor** has an outdoor instrument model, but its owner labels it "Koramangala Indoor". The diurnal shape (morning-traffic peak, afternoon low, range 6–93) looks outdoor. All 10 government (CPCB/KSPCB) stations in Bengaluru have been silent for ~108 h, which is itself a live example of no-data handling. Fallback: CPCB BTM Layout (5548) if it resumes.
- Three of five stations are **low-cost sensors**, which read high in humid air. Detection is baseline-relative per station, so a consistent bias mostly cancels out. Absolute severity bands inherit the bias, which is noted in the architecture note.
- **Pollutant: PM2.5 only in v1.** It's the only pollutant all five stations measure (AirGradient units measure particulates only). The schema is multi-parameter.

---

## 3. AQI standard (decision)

- **Detection runs on raw PM2.5 concentration** (µg/m³), log-transformed, per station. That's what the learned baseline models. AQI is not used for detection.
- **AQI is used for severity bands and for message wording.** Standard: **US EPA AQI with the 2024 PM2.5 breakpoints, using NowCast** for the hourly value. NowCast is designed for hourly reporting and reacts quickly to rising smoke and dust. India's NAQI uses 24-hour averages and needs 16 hours of data, which lags too much for hourly nudges. It can appear as a secondary label for Indian users. Confirmed by the S-B research, which verified the 2024 breakpoints and the NowCast formula (S-B §2).
- **Absolute floors** (FR-SENS-3) are expressed in AQI bands, so "unhealthy" means the same thing in every city, while "unusual" stays station-relative.

---

## 4. Ingestion design

- **Schedule:** poll every hour at `:20` UTC (after typical publication lag). For each tracked sensor, fetch a **trailing 24 h window** of `/hours` and upsert. That's 5 calls/hour in steady state, far under limits. The 24 h overlap is what catches late and back-filled hours (FR-DET-6, FR-ING-3).
- **Backfill** on first run, and whenever a sensor's last stored hour is older than 24 h: page through up to 90 days (≤ 3 pages × 5 sensors).
- **Idempotency:** the natural key is `(sensor_id, period_end_utc)`. A re-fetch with the same value is a no-op. A changed value is stored as a **revision** (below), never an overwrite, so replay stays faithful.
- **Rate-limit handling:** read `x-ratelimit-remaining`, back off on 429, never retry tight. Every run writes an `ingestion_runs` row.
- **After each run**, the pipeline evaluates every hour that was *new or revised* in the run, not just the latest one (FR-DET-6: gaps and late data).

---

## 5. Storage schema

Portable SQL (SQLite for local and tests, Postgres when hosted). All timestamps are UTC `TIMESTAMP`; local time is derived from `stations.timezone`. JSON columns hold structured traces that are read by humans and the decision viewer, never joined on.

```sql
-- Reference data ---------------------------------------------------------
CREATE TABLE stations (
  id               INTEGER PRIMARY KEY,         -- OpenAQ location id
  city             TEXT NOT NULL UNIQUE,        -- one primary station per city (requirements §5)
  name             TEXT NOT NULL,
  provider         TEXT NOT NULL,
  instrument       TEXT,
  is_reference     BOOLEAN NOT NULL,            -- OpenAQ isMonitor
  timezone         TEXT NOT NULL,               -- IANA, e.g. Asia/Kolkata
  lat REAL, lon REAL,
  license          TEXT, attribution TEXT,      -- CC BY 4.0 / US Public Domain / ODC-BY
  active           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sensors (
  id               INTEGER PRIMARY KEY,         -- OpenAQ sensor id
  station_id       INTEGER NOT NULL REFERENCES stations(id),
  parameter        TEXT NOT NULL,               -- 'pm25' (v1), extensible
  units            TEXT NOT NULL,
  UNIQUE (station_id, parameter)
);

-- Readings: append-only revisions so replay can ask "what did we know at T?" (FR-ING-3a, FR-EVAL-5)
CREATE TABLE readings (
  sensor_id        INTEGER NOT NULL REFERENCES sensors(id),
  period_end       TIMESTAMP NOT NULL,          -- OpenAQ period.datetimeTo (the reading's time)
  period_start     TIMESTAMP NOT NULL,
  value            REAL,                        -- hour mean, raw (no cleaning here)
  coverage_pct     REAL,                        -- OpenAQ coverage.percentCoverage
  ingested_at      TIMESTAMP NOT NULL,          -- when WE stored this version
  run_id           INTEGER REFERENCES ingestion_runs(id),
  PRIMARY KEY (sensor_id, period_end, ingested_at)
);
-- "As of T" = for each (sensor_id, period_end), the row with max ingested_at <= T.
-- Live = as of now. A view `readings_current` exposes the latest version.

CREATE TABLE ingestion_runs (
  id               INTEGER PRIMARY KEY,
  started_at       TIMESTAMP NOT NULL, finished_at TIMESTAMP,
  kind             TEXT NOT NULL,               -- 'hourly' | 'backfill' | 'replay-load'
  sensor_id        INTEGER REFERENCES sensors(id),
  window_from      TIMESTAMP, window_to TIMESTAMP,
  rows_fetched     INTEGER, rows_new INTEGER, rows_revised INTEGER,
  newest_period_end TIMESTAMP,                  -- freshness: lag = started_at - newest_period_end
  status           TEXT NOT NULL,               -- 'ok' | 'partial' | 'error'
  error            TEXT,
  ratelimit_remaining INTEGER
);

-- Users and rules ---------------------------------------------------------
CREATE TABLE users (
  id               TEXT PRIMARY KEY,            -- e.g. 'priya-blr'
  display_name     TEXT NOT NULL,
  station_id       INTEGER NOT NULL REFERENCES stations(id),  -- v1: one location (requirements §8)
  persona          JSON NOT NULL                -- e.g. {"conditions":["asthma"],"habits":["morning run 06:30"]}; feeds message wording
);

CREATE TABLE user_rules (                       -- declarative; exact rule format is defined in S-C
  id               INTEGER PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id),
  version          INTEGER NOT NULL,
  source           TEXT NOT NULL,               -- 'default' | 'user' | 'learned' (future)
  rules            JSON NOT NULL,
  created_at       TIMESTAMP NOT NULL,
  UNIQUE (user_id, version)
);
-- Every decision records the rules version it used, so old decisions stay explainable after rules change.

-- Detection ---------------------------------------------------------------
CREATE TABLE baselines (                        -- learned per-station model state, snapshotted
  id               INTEGER PRIMARY KEY,
  sensor_id        INTEGER NOT NULL REFERENCES sensors(id),
  fitted_at        TIMESTAMP NOT NULL,          -- simulated time in replay
  trained_through  TIMESTAMP NOT NULL,          -- last reading used
  model            TEXT NOT NULL,               -- model id + version (S-C)
  params           JSON NOT NULL                -- e.g. hour-of-day medians, MAD, EWMA/CUSUM state
);

CREATE TABLE station_scores (                   -- U2 SCORE: one row per (sensor, evaluated hour). Shared by all users:
  id               INTEGER PRIMARY KEY,         -- contains NO user sensitivity (explainer §2, FR-SENS-4)
  sensor_id        INTEGER NOT NULL REFERENCES sensors(id),
  period_end       TIMESTAMP NOT NULL,          -- the hour evaluated
  evaluated_at     TIMESTAMP NOT NULL,          -- clock time of evaluation (injected)
  baseline_id      INTEGER REFERENCES baselines(id),
  z                REAL,                        -- unusual: distance from normal for this hour of day
  ewma             REAL,                        -- smoothed z (lambda 0.3)
  cusum            REAL,                        -- accumulated excess (resets after an "elevated" signal)
  slope_6h         REAL,                        -- Theil-Sen slope of log1p(PM2.5) over 6h
  nowcast          REAL,                        -- harmful: NowCast PM2.5
  band             TEXT,                        -- EPA band of nowcast
  typical_band     TEXT,                        -- EPA band of the station's 14-day median
  quality          JSON,                        -- coverage, gap info, glitch checks applied (S2)
  evidence         JSON NOT NULL,               -- input window, expected vs observed
  UNIQUE (sensor_id, period_end, evaluated_at)
);
-- Per-user triggers (D1: event kind, the user's scaled bars, near-misses) are NOT stored here.
-- They are part of each user's decision trace, because they depend on the user's sensitivity.

-- Episodes, decisions, notifications ---------------------------------------
CREATE TABLE episodes (                         -- per user + station + parameter (FR-DEDUP-1)
  id               INTEGER PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id),
  sensor_id        INTEGER NOT NULL REFERENCES sensors(id),
  opened_at        TIMESTAMP NOT NULL, closed_at TIMESTAMP,
  state            TEXT NOT NULL,               -- NORMAL | ACTIVE | RECOVERING | CLOSED (S-C §5)
  close_reason     TEXT,                        -- 'calm' | 'no_data_timeout' (closed quietly after 24h silence)
  peak_value       REAL, peak_band TEXT,
  last_notified_at TIMESTAMP, last_notified_band TEXT, last_notified_kind TEXT,
  notifications_sent INTEGER NOT NULL DEFAULT 0,
  cooldown_until   TIMESTAMP
);

CREATE TABLE decisions (                        -- THE observability record (FR-OBS-1/2): one per user per evaluation
  id               INTEGER PRIMARY KEY,
  evaluated_at     TIMESTAMP NOT NULL,
  period_end       TIMESTAMP NOT NULL,
  user_id          TEXT NOT NULL REFERENCES users(id),
  sensor_id        INTEGER NOT NULL REFERENCES sensors(id),
  rules_version    INTEGER NOT NULL,
  episode_id       INTEGER REFERENCES episodes(id),
  score_ids        JSON,                        -- station_scores rows considered
  outcome          TEXT NOT NULL,               -- 'sent' | 'held' | 'suppressed' | 'no_event'
  reason_code      TEXT NOT NULL,               -- machine-readable, e.g. 'DEDUP_SAME_BAND', 'QUIET_HOURS_HELD' (S-C §9)
  trigger          TEXT NOT NULL DEFAULT 'data', -- 'data' (new/revised hours) | 'clock' (hourly tick, check-in, release)
  reason           TEXT NOT NULL,               -- human-readable sentence
  trace            JSON NOT NULL,               -- ordered layer steps (D1..D8) with inputs, scaled bars, results
  replay_run       TEXT                         -- null for live; replay id for evaluation runs
);

CREATE TABLE notifications (
  id               INTEGER PRIMARY KEY,
  decision_id      INTEGER NOT NULL REFERENCES decisions(id),
  user_id          TEXT NOT NULL REFERENCES users(id),
  created_at       TIMESTAMP NOT NULL,
  deliver_after    TIMESTAMP NOT NULL,          -- > created_at when held by quiet hours
  delivered_at     TIMESTAMP,                   -- v1 "delivery" = becomes visible in the API/feed
  kind             TEXT NOT NULL,               -- event kind that triggered it
  body             TEXT NOT NULL,
  next_action      TEXT NOT NULL,
  context_facts    JSON NOT NULL,               -- the facts the composer was given (FR-MSG-5)
  generator        TEXT NOT NULL                -- 'llm:<model>' | 'template'
);

CREATE TABLE feedback (                         -- FR-FB: recorded only, no learning in v1
  id               INTEGER PRIMARY KEY,
  notification_id  INTEGER NOT NULL REFERENCES notifications(id),
  user_id          TEXT NOT NULL REFERENCES users(id),
  action           TEXT NOT NULL,               -- 'acted' | 'dismissed' | 'not_useful'
  at               TIMESTAMP NOT NULL
);
```

How the requirements land in the schema:
- **Explain any decision from stored data alone (NFR-2):** `decisions.trace` (the user's triggers and every layer's result) plus `score_ids` → `station_scores.evidence` → `readings` as of `evaluated_at`, with `rules_version` and `baseline_id` pinning the exact config and model.
- **Missing nudges are debuggable (FR-OBS-2):** a `decisions` row exists for *every* user × hour, including `no_event`, written by the data run or the clock tick (FR-CLK-1). Near-misses are recorded in the user's trace.
- **Replay (FR-EVAL):** the replay loads `data/samples/` into `readings` with synthetic `ingested_at` values matching the original publication lag. Replay decisions carry `replay_run`, so they never mix with live ones.
- **Restart-safe (NFR-4):** episodes, cooldowns and baselines are rows, not memory.

---

## 6. Recorded sample in the repo

`data/samples/openaq_pm25_hourly_90d.csv` holds about 13.5k rows: 90 days of hourly PM2.5 for the 5 tracked stations plus the 2 fixtures (Mumbai glitches, Delhi AirNow gaps). Columns: `location_id, sensor_id, period_start_utc, period_end_utc, value_ugm3, percent_coverage`. `data/samples/stations.json` holds station metadata and licences.

Licences: AirGradient data is **CC BY 4.0** (attribution to each sensor owner, listed in `stations.json`), AirNow is **US Public Domain**, and EEA is **ODC-BY**. The README must carry an attribution line: "Air quality data from OpenAQ (openaq.org) and the original providers listed in data/samples/stations.json."

---

## 7. Left for S-C

The detector model and its state in `baselines.params`; event kinds (spike / climb / elevated / clearing / floor); severity band thresholds; the episode state machine; the user rule format in `user_rules.rules`; `reason_code` vocabulary; and how replay labels "interesting moments".
