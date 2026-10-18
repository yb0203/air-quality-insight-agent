# S-C — Rule engine and detection spec

Status: draft for review · 2026-10-18 · Implements FR-DET, FR-SENS, FR-RULE, FR-DEDUP, FR-OBS-1/2, FR-EVAL-3 in [requirements.md](../requirements.md). Built on [S-A](S-A-openaq-and-schema.md) (data) and [S-B](S-B-rule-engine-research.md) (research).

Every number in this spec was calibrated on the 90-day sample in `data/samples/` (section 10). The replay harness (FR-EVAL) is the tool for changing them later.

---

## 1. Design principles

1. **Hand-rolled, typed, ordered pipeline.** Per S-B §3, no rule-engine library models holds, cooldowns or episodes, which are the hard parts. Each stage is a pure function `(inputs, state, now) → (outcome, reason_code, evidence)`. The order is fixed (section 6). This is the opposite of a generic engine: a small vocabulary of dials, evaluated the same way every time.
2. **Statistics decide "unusual", health decides "worth saying".** The learned detector is station-relative (FR-SENS-1). The EPA AQI bands are absolute (FR-SENS-3). An event must pass both to reach a user. That's how a clean city gets a lower bar without notifying anyone about harmless noise.
3. **Recompute, don't accumulate.** Every evaluation recomputes the baseline (14 days) and the short-term statistics (72 h) from the readings *known at that moment*. No incremental detector state is persisted. Live and replay therefore make identical decisions (FR-EVAL-5), and late or back-filled data is re-evaluated automatically (FR-DET-6).
4. **Time is injected.** No stage reads the wall clock.
5. **Every stage writes its reason.** A decision's `trace` is the ordered list of stage results. A missing notification is explained by the stage that stopped it (FR-OBS-2).

---

## 2. Preprocessing and data quality

Per sensor, per evaluated hour `t` (the `period_end` of a reading):

| Check | Rule | Effect | Reason code |
|---|---|---|---|
| Invalid value | `value < 0` or `value > 1000` µg/m³ | excluded | `DQ_INVALID` |
| Low coverage | OpenAQ `percent_coverage < 75` | excluded from scoring, kept for display | `DQ_LOW_COVERAGE` |
| Stuck sensor | identical value for ≥ 6 consecutive hours | those hours excluded | `DQ_STUCK` |
| Isolated glitch | `v_t > 3·max(v_{t-1},1)` and `v_t > 3·max(v_{t+1},1)` and `v_t − v_{t-1} > 20` | excluded; evidence keeps it | `DQ_SUSPECT` |
| Stale | newest reading older than 3 h | short-term state carries over (keep last state) | — |
| No data | newest reading older than 3 h *at evaluation time*, or < 72 h of history in the 14-day window | no detection; episodes neither open nor close | `NO_DATA` / `NO_BASELINE` |
| Gap reset | gap > 3 h between consecutive readings | EWMA, CUSUM and spike memory restart after the gap | — |

The glitch check needs hour `t+1`, so the newest hour is "provisionally clean" and re-evaluated next hour. That costs nothing extra, because spikes need 2-of-3 confirmation anyway. In calibration, Mumbai's unflagged 784–982 µg/m³ one-hour glitches were all caught as `DQ_SUSPECT` (8 hours over 58 days). No other station tripped it more than once.

---

## 3. Learned baseline (per sensor)

- Transform: `y = log1p(PM2.5)`. Makes a doubling look the same in Helsinki and Delhi.
- For each local hour-of-day `h`: `m_h = median(y)` and `s_h = 1.4826 · MAD(y)` over the trailing 14 days of clean readings.
- With fewer than 7 samples for that hour, shrink toward the all-hours median and MAD, weighted by `n/7`. With fewer than 2 samples, use all-hours.
- Floor: `s_h ≥ 0.15`, so flat, clean stations don't fire on sensor noise.
- Minimum history: 72 clean hours in the window, else `NO_BASELINE`.
- **Typical band** of the station = the EPA band of its 14-day median concentration. Used by recovery (section 4.4) and the check-in. Calibrated: Helsinki and Los Angeles = Good or Moderate, Bengaluru = Moderate, Dubai and Delhi = Unhealthy for Sensitive Groups (USG).
- Snapshot written to `baselines` once per evaluation, with the 24 `(m_h, s_h)` pairs and the typical band.

Score: `z_t = (y_t − m_h) / s_h`.

---

## 4. Detectors (station-level, scaled per user)

User sensitivity multiplies every detector threshold by `k`: low = 1.25, default = 1.0, high = 0.75 (FR-SENS-2).

### 4.1 Spike (FR-DET-3)
`z ≥ 3.5·k` in **2 of the last 3** clean hours. Spikes are scored on raw hourly values, not NowCast, because NowCast lags (S-B §2).

### 4.2 Sustained trend (FR-DET-2)
`EWMA_t = 0.3·z_t + 0.7·EWMA_{t−1}` (seeded at the first hour of the 72 h window or after a gap). Fires when `EWMA > 1.26·k` for **3 consecutive hours** (NIST EWMA limit with λ = 0.3, L = 3). The 6 h Theil–Sen slope of `y` is computed as message evidence ("climbing since 7am"), not as a gate.

### 4.3 Slow-burn drift (FR-DET-6, missed triggers)
Upper CUSUM `C_t = max(0, C_{t−1} + z_t − 0.5)`. Fires when `C > 8·k`, then **resets to 0** (one-shot signal). It counts only while `EWMA ≥ 0.5`, so a drift that has already faded opens nothing. Calibration: `h = 5` (S-B's starting value) let drift alone open about half of all episodes. `h = 8` cut notifications by about 20% while keeping every multi-day build-up.

### 4.4 Return to normal (FR-DET-4)
An open episode is **calm** for an hour when all three hold: `EWMA < 0.5`, no detector fired, and the NowCast band ≤ the station's typical band. **4 consecutive calm hours** close it (recovery dwell, S-B's "Recovering" state). Requiring the typical band stops "back to normal" from going out while the air is still unhealthy. Calibration pass 2 sent several of those before this condition existed.

### 4.5 Absolute floor (FR-SENS-3)
Fires on an **upward crossing**: NowCast is at or above the user's `alert_band` in 2 of the last 3 hours, and it was below that band 6 hours earlier. Edge-triggered, so Delhi sitting at USG all week doesn't open an endless episode, while a jump into Very Unhealthy is never missed even if it's "normal for the season".

### 4.6 Near-misses (FR-DET-6)
Logged to `detections` with `fired = false` when `z ≥ 0.8·spike bar`, `EWMA ≥ 0.8·trend bar`, or `C ≥ 0.8·drift bar`. Visible in the decision viewer, never notified.

### 4.7 Severity
NowCast PM2.5 (S-B §2: 12 h weights, w clamped to [0.5, 1], requires 2 of the 3 most recent hours) → US EPA 2024 bands: Good ≤ 9.0, Moderate ≤ 35.4, USG ≤ 55.4, Unhealthy ≤ 125.4, Very Unhealthy ≤ 225.4, Hazardous above. **Severe** = Very Unhealthy or worse.

---

## 5. Episodes (FR-DEDUP-1/2)

One episode per `(user, sensor)`. Detection is shared per station, but triggers depend on the user's `k` and floors, so episodes are per user. This mirrors a PagerDuty `dedup_key` lifecycle.

```
             trigger fired AND band ≥ relevance_floor
   NORMAL ─────────────────────────────────────────────► ACTIVE
     ▲                                                     │  ▲
     │ 6 h after close                    calm hour        │  │ trigger or non-calm hour
     │ (flap window expires)                               ▼  │
   CLOSED ◄──────────── 4 consecutive calm hours ───── RECOVERING
     │
     └── trigger within 6 h of close ──► same episode reopens as ACTIVE (flap guard, no new "opened" notice)

   NO_DATA overlay: when the sensor has no usable data, state is frozen. Nothing opens, closes, or notifies.
   When data returns, the gap is evaluated hour by hour.
```

Episode fields (schema in S-A): `opened_at`, `state`, `kinds` seen (spike/trend/drift/floor), `peak_value`, `peak_band`, `last_notified_{at,band,kind}`, `notifications_sent`, `cooldown_until`, `closed_at`.

---

## 6. The per-user evaluation pipeline

Runs once per user for every newly ingested or revised hour (and in replay, for every simulated hour). Stages run in this order. The first terminal outcome stops the pipeline, and every stage appends to `trace`.

| # | Stage | Passes when | Otherwise → outcome · reason code |
|---|---|---|---|
| 1 | **Data** | usable reading and baseline (section 2) | `no_event` · `NO_DATA` / `NO_BASELINE` / `DQ_*` |
| 2 | **Detect** | compute triggers with user `k`, floors and near-misses | — (never terminal) |
| 3 | **Episode update** | apply the section 5 state machine; yields a *candidate*: `opened`, `escalated`, `recovered`, or none | `no_event` · `NO_TRIGGER` / `EPISODE_CONTINUES` |
| 4 | **Relevance** | `opened`/`escalated`: NowCast band ≥ `relevance_floor` | `suppressed` · `BELOW_RELEVANCE` |
| 5 | **Meaningful change** | `opened` = first notice of the episode. `escalated` = band ≥ last notified band + 1. `recovered` = the episode was notified **and** (lasted ≥ 12 h **or** peaked at USG+ above its typical band) | `suppressed` · `DEDUP_SAME_BAND` / `RECOVERY_NOT_WORTH_SAYING` |
| 6 | **Inhibition** | at most one notice per user per evaluation: `escalated` > `opened` > `recovered`. A spike inside an active trend episode says nothing unless the band escalates (handled in stage 5) | `suppressed` · `INHIBITED_BY_<kind>` |
| 7 | **Cooldown and decay** | time since the user's last notice ≥ the current gap. The gap starts at 6 h and **doubles with each notice in the same episode** (6 → 12 → 24 h), resetting when the episode closes. Daily cap: 3 non-severe notices per user per local day. **Severe escalations bypass both** | `suppressed` · `COOLDOWN` / `DAILY_CAP` |
| 8 | **Quiet hours** | outside the user's quiet window, or the band ≥ `breakthrough_band` | `held` · `QUIET_HOURS_HELD` |
| 9 | **Compose and emit** | message composed (section 8) | `sent` |

**Releasing held notices.** At the end of quiet hours, all held candidates for a user collapse into **one** notice describing the *current* state. Example: "Overnight the air got worse, peaking around 2am; it's easing now…". If the episode closed overnight and was never notified, nothing is sent (`HELD_EXPIRED`). The released notice goes through stages 5–7 again at release time.

**Daily check-in** (`check_in.cron`, optional). At the scheduled local time, a separate path evaluates the last 8 h. It speaks only if all three hold: the NowCast band ≥ `relevance_floor`; `EWMA ≥ 1.0` or the band is above the station's typical band; and no notice went out in the last 6 h. Otherwise it logs `no_event · CHECKIN_QUIET`. It is never a fixed daily report. Check-in notices count toward the daily cap.

---

## 7. User rule format (FR-RULE)

Declarative JSON in `user_rules.rules`. Versioned, with `source` = `default | user | learned`. Every field is optional, and missing fields fall back to defaults.

```json
{
  "location":        { "station_id": 4588 },
  "pollutants":      ["pm25"],
  "sensitivity":     "high",
  "relevance_floor": "moderate",
  "alert_band":      "unhealthy",
  "quiet_hours":     { "start": "22:00", "end": "07:00", "breakthrough_band": "very_unhealthy" },
  "check_in":        { "cron": "30 6 * * *" },
  "cooldown":        { "base_gap_hours": 6, "max_per_day": 3 }
}
```

| Field | Default | Notes |
|---|---|---|
| `sensitivity` | `default` (k = 1.0) | `low` 1.25 · `high` 0.75 |
| `relevance_floor` | `moderate` | Minimum band for a notice about a worsening. Clean-city users still hear about 4 → 15 µg/m³ (Good → Moderate); nobody hears about 3 → 5. |
| `alert_band` | `very_unhealthy`; `unhealthy` for `sensitivity: high` | Absolute floor, edge-triggered (section 4.5) |
| `quiet_hours` | `22:00–07:00`, breakthrough at `very_unhealthy` | Local time of the user's station |
| `check_in.cron` | none | Standard 5-field cron in station local time. Library choice is left to the builder. |
| `cooldown` | 6 h base, 3 per day | Decay doubles per notice within an episode |

Validation: unknown fields are rejected, bands must be valid EPA band names, and the cron must parse. Invalid rules fall back to the previous version and log `RULES_INVALID`.

**Extension path (not v1).** Future rule inputs such as movement or home-system state are added as new typed fields with their own pipeline stage. Free-form conditions, if ever needed, go in an `extra_conditions` block using the `business-rules` `all/any` JSON shape, evaluated by the `rule-engine` package (S-B §3). The learning layer writes a new `user_rules` version with `source: learned`, so its changes are visible and reversible.

---

## 8. Message composition contract (FR-MSG)

The pipeline hands the composer a **structured insight**, never raw data:

```json
{
  "kind": "opened | escalated | recovered | check_in | released_after_quiet_hours",
  "trigger_kinds": ["trend", "drift"],
  "city": "Delhi", "local_time": "2026-10-18T08:00+05:30",
  "now": { "pm25": 142, "band": "very_unhealthy", "aqi": 203 },
  "typical_for_this_hour": { "pm25": 48, "band": "usg" },
  "episode": { "started": "since 2am", "hours": 6, "peak": { "pm25": 151, "at": "6am" } },
  "history_facts": ["worst since 13 Oct", "third bad morning this week"],
  "trend": { "direction": "rising", "per_hour": 9.5 },
  "user": { "name": "Arjun", "persona": { "habits": ["morning run 06:30"], "conditions": [] } },
  "action_candidates": ["skip the outdoor run", "keep windows closed", "wear an N95 if you go out"]
}
```

- **History facts** are computed deterministically: "worst since `<date>`", "Nth bad day this week", "back to normal after N hours/days", "first time this month". FR-MSG-2 requires at least one whenever the episode or history supports it, which is always true for trend, spike and recovery.
- **One next action** comes from a fixed action catalogue keyed by `(kind, band, persona habits, local time of day)`. The composer picks exactly one, and doesn't invent others.
- **Generator:** an LLM writes the sentence from this JSON (e.g. Claude Haiku), and the output is validated: ≤ 220 characters, mentions the action, cites only numbers and facts present in the input. On failure or no API key, a **template fallback** composes from the same facts. `notifications.generator` records which one ran. Provider wiring belongs in the architecture note.

---

## 9. Decision log vocabulary (FR-OBS)

`outcome` ∈ `sent | held | suppressed | no_event`. Reason codes:

`NO_DATA`, `NO_BASELINE`, `DQ_INVALID`, `DQ_LOW_COVERAGE`, `DQ_STUCK`, `DQ_SUSPECT`, `NO_TRIGGER`, `EPISODE_CONTINUES`, `BELOW_RELEVANCE`, `DEDUP_SAME_BAND`, `RECOVERY_NOT_WORTH_SAYING`, `INHIBITED_BY_<KIND>`, `COOLDOWN`, `DAILY_CAP`, `QUIET_HOURS_HELD`, `HELD_RELEASED`, `HELD_EXPIRED`, `CHECKIN_QUIET`, `RULES_INVALID`, `SENT_OPENED`, `SENT_ESCALATED`, `SENT_RECOVERED`, `SENT_CHECK_IN`, `SENT_SEVERE_BYPASS`.

Each `trace` entry has the form `{stage, passed, reason_code, inputs, values}`, for example `{stage: "cooldown", passed: false, reason_code: "COOLDOWN", values: {last_sent: "...", gap_h: 12, elapsed_h: 7.5}}`. The decision viewer renders the trace as plain sentences.

---

## 10. Calibration on the 90-day sample (2026-10-18)

Throwaway replay of sections 2–6 (without quiet hours or the check-in) on `data/samples/`, default user, k = 1.0:

| Station | Episodes / 90 d | Notices per week | of which open / escalate / recover | Median episode |
|---|---|---|---|---|
| Helsinki | 10 | 1.5 | 10 / 0 / 8 | 24 h |
| Los Angeles | 14 | 2.1 | 14 / 0 / 11 | 18 h |
| Bengaluru | 15 | 2.4 | 15 / 2 / 12 | 19 h |
| Dubai | 16 | 2.4 | 16 / 2 / 12 | 27 h |
| Delhi (low-cost) | 20 | 3.5 | 20 / 6 / 17 | 18 h |
| Delhi (AirNow reference, fixture) | 20 | 3.3 | — | 9 h |
| Mumbai (glitch fixture) | 11 | 2.7 | — | 12 h |

Sensitive users (k = 0.75) get 1.7–4.3 notices a week. What the three iterations taught us, and which is now baked into the spec:
1. CUSUM must reset after signalling. Otherwise episodes never close (pass 1: Bengaluru stayed "open" for 20 days).
2. Recovery must require the station's typical band. Otherwise "back to normal" goes out while the air is still unhealthy.
3. Drift at `h = 5` is too eager. `h = 8` plus the recovery-worthiness rule took Delhi from 5.8 to 3.5 notices a week.
4. Delhi's low-cost sensor and its reference monitor give near-identical rates. The baseline-relative design absorbs sensor bias, as S-A predicted.

The harness (FR-EVAL) replaces this table with caught / missed / false-alarm counts against reference labels.

---

## 11. Evaluation harness labels (FR-EVAL-3)

- **Reference labels:** `ruptures` PELT (l2 cost on `y`) over the full sample marks change points. An "interesting moment" is an upward change point whose new segment mean is ≥ 1 band above the previous one, or ≥ 2× the previous mean, and lasts ≥ 3 h. Hand labels add known events (e.g. Helsinki 24 Aug smoke, Mumbai glitches as **negatives**).
- **Caught** = a `sent` or `held` decision within 6 h after the moment starts. **Missed** = none. **False alarm** = a sent notice for an `opened` episode with no labelled moment within ±6 h. Glitch fixtures must produce zero notices.
- **Report:** per station and per persona: caught, missed, false alarms, notices per week, median time-to-notify. Plus the near-misses that sat closest to each missed moment, for tuning.

---

## 12. Parameter table (all defaults in one place)

| Parameter | Value | Section |
|---|---|---|
| Baseline window / min history | 14 days / 72 h | 3 |
| MAD floor (log1p units) | 0.15 | 3 |
| Spike | z ≥ 3.5·k, 2 of 3 h | 4.1 |
| Trend | EWMA λ 0.3 > 1.26·k for 3 h | 4.2 |
| Drift | CUSUM k_ref 0.5, h 8·k, reset after signal, needs EWMA ≥ 0.5 | 4.3 |
| Recovery | EWMA < 0.5 and band ≤ typical, 4 consecutive hours | 4.4 |
| Flap window | 6 h | 5 |
| Gap reset / no-data | > 3 h | 2 |
| Cooldown | 6 h base, doubling within an episode, 3 per day, severe bypass | 6 |
| Recovery notice worthiness | ≥ 12 h or peak USG+ above typical | 6 |
| Low coverage | < 75% | 2 |
| Glitch | 3× both neighbours and +20 µg/m³ | 2 |
| Sensitivity k | 1.25 / 1.0 / 0.75 | 4 |
