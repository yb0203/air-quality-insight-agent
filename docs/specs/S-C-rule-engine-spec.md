# S-C — Rule engine and detection spec

Status: approved · updated 2026-10-18 from the closed [explainer](../explainer.md) · Implements FR-CLK, FR-DET, FR-SENS, FR-RULE, FR-DEDUP, FR-OBS-1/2, FR-EVAL-3 in [requirements.md](../requirements.md). Built on [S-A](S-A-openaq-and-schema.md) (data) and [S-B](S-B-rule-engine-research.md) (research).

This spec gives the exact logic for layers S2, U1, U2, D1–D8 and RECORD from the [explainer](../explainer.md). The explainer gives the why and the diagrams; this gives the numbers. Every number was calibrated on the 90-day sample in `data/samples/` (section 10). The replay harness (FR-EVAL) is how they get changed later.

| Explainer layer | This spec |
|---|---|
| S2 VALIDATE | §2 |
| U1 LEARN | §3 |
| U2 SCORE | §4 |
| D1 TRIGGER | §5 |
| D2 EPISODE | §6 |
| D3–D8 restraint, CLOCK | §7 |
| User rules | §8 |
| A1 COMPOSE (contract) | §9 |
| RECORD (vocabulary) | §10 |

---

## 1. Design principles

1. **Hand-rolled, typed, ordered pipeline.** No rule-engine library models holds, pacing or episodes, which are the hard parts (S-B §3). Each layer is a pure function `(inputs, state, now) → (outcome, reason_code, evidence)`, run in a fixed order (§7).
2. **Station work is shared, person work is not.** S2–U2 compute facts about a station once per hour. They're stored in `station_scores` and never depend on any user. Everything personal starts at D1.
3. **"Unusual" and "harmful" are separate.** The learned score decides unusual. The EPA band decides harmful. A notice needs the right combination (explainer §6).
4. **Recompute, don't accumulate.** Every evaluation recomputes the baseline (14 days) and the short-term statistics (72 h) from the readings *known at that moment*. Replay therefore equals live (FR-EVAL-5), and late data is re-evaluated automatically (FR-DET-6).
5. **Time is injected.** No layer reads the wall clock.
6. **Every layer writes its reason** into the decision `trace`, including stubs (FR-OBS-2).

---

## 2. S2 VALIDATE

Per sensor, per evaluated hour `t` (the `period_end` of a reading):

| Check | Rule | Effect | Reason code |
|---|---|---|---|
| Invalid value | `value < 0` or `value > 1000` µg/m³ | excluded | `DQ_INVALID` |
| Low coverage | OpenAQ `percent_coverage < 75` | excluded from scoring, kept for display | `DQ_LOW_COVERAGE` |
| Stuck sensor | identical value for ≥ 6 consecutive hours | those hours excluded | `DQ_STUCK` |
| Isolated glitch | `v_t > 3·max(v_{t-1},1)` and `v_t > 3·max(v_{t+1},1)` and `v_t − v_{t-1} > 20` | excluded; evidence keeps it | `DQ_SUSPECT` |
| Gap reset | gap > 3 h between consecutive readings | EWMA, CUSUM and spike memory restart after the gap | — |
| No data | newest reading older than 3 h at evaluation time | no scoring; episodes frozen (§6) | `NO_DATA` |
| No baseline | < 72 clean hours in the 14-day window | no scoring | `NO_BASELINE` |

The glitch check needs hour `t+1`, so the newest hour is provisionally clean and re-checked next hour. Calibration: Mumbai's unflagged one-hour glitches of 784–982 µg/m³ were all caught (8 hours in 58 days). No tracked station tripped the check more than once.

---

## 3. U1 LEARN (per sensor)

- Transform: `y = log1p(PM2.5)`.
- For each local hour of day `h`: `m_h = median(y)` and `s_h = 1.4826 · MAD(y)` over the trailing 14 days of clean readings.
- With fewer than 7 samples for that hour, shrink toward the all-hours median and MAD with weight `n/7`. With fewer than 2 samples, use all-hours.
- Floor: `s_h ≥ 0.15`.
- **Typical band** = the EPA band of the station's 14-day median concentration. Calibrated: Helsinki = Good; Los Angeles and Bengaluru = Moderate; Dubai and Delhi = USG.
- Snapshot written to `baselines` once per evaluation.

---

## 4. U2 SCORE (per sensor, shared, no user parameters)

Written to `station_scores` for every evaluated hour:

| Score | Definition |
|---|---|
| `z` | `(y_t − m_h) / s_h` |
| `ewma` | `0.3·z_t + 0.7·ewma_{t−1}`, seeded at the start of the 72 h window or after a gap |
| `cusum` | `max(0, cusum_{t−1} + z_t − 0.5)`. Resets to 0 after any user's "elevated" signal would fire at the default bar. Per-user bars are evaluated on a per-user copy in D1, so the shared value stays sensitivity-free. |
| `slope_6h` | Theil–Sen slope of `y` over the last 6 hours (log units per hour) |
| `nowcast` | EPA NowCast PM2.5 (12 h weights, w clamped to [0.5, 1], requires 2 of the 3 most recent hours) |
| `band` | US EPA 2024 band of `nowcast`: Good ≤ 9.0, Moderate ≤ 35.4, USG ≤ 55.4, Unhealthy ≤ 125.4, Very Unhealthy ≤ 225.4, Hazardous above. **Severe** = Very Unhealthy or worse. |
| `typical_band` | from U1 |

> Implementation note: the CUSUM reset depends on the bar, and the bar depends on the user. The builder computes the shared `cusum` series once, and each user's D1 re-runs the (cheap) one-line CUSUM recursion over the same 72 h `z` series with that user's bar. `station_scores` keeps the default-bar series for display.

---

## 5. D1 TRIGGER (per user)

User sensitivity sets `k`: `low` = 1.25, `default` = 1.0, `high` = 0.75. It multiplies every bar below. It never changes a score.

| Kind | Fires when | Brief |
|---|---|---|
| **spike** | `z ≥ 3.5·k` in **2 of the last 3** clean hours | B2b |
| **climb** | `ewma > 1.26·k` for **3 consecutive hours** **and** `slope_6h > 0.01` (rising about 1%+ per hour) | B2a |
| **elevated** | the user's CUSUM `> 8·k`, counted only while `ewma ≥ 0.5`. One-shot: the user's CUSUM resets after it fires. | B2d (missed triggers) |
| **floor** | NowCast at or above the user's `alert_band` in 2 of the last 3 hours, and below it 6 hours earlier (upward crossing only) | FR-SENS-3 |
| **clearing** | an open episode has a calm hour: `ewma < 0.5`, no kind above fired, and `band ≤ typical_band` (counted by D2) | B2c |

**One label per event** (FR-DET-8): when several fire in the same hour, the label is spike, then climb, then elevated, then floor. The label drives wording.

**Near-misses** are written to the user's trace, never notified: `z ≥ 0.8·spike bar`, or `ewma ≥ 0.8·climb bar` (with a rising slope), or CUSUM `≥ 0.8·elevated bar`.

---

## 6. D2 EPISODE (per user, per sensor)

```
             trigger fired AND band ≥ Moderate (the user's relevance_floor)
   NORMAL ─────────────────────────────────────────────────────────────► ACTIVE
     ▲                                                                    │  ▲
     │ 6 h after close                                   calm hour        │  │ trigger or non-calm hour
     │ (flap window expires)                                              ▼  │
   CLOSED ◄────────────────── 4 consecutive calm hours ────────────── RECOVERING
     ▲ │
     │ └── trigger within 6 h of close ──► same episode reopens as ACTIVE (flap guard)
     │
     └──── 24 h of NO_DATA ──► closes quietly: close_reason = 'no_data_timeout', no notice

   NO_DATA under 24 h: state frozen. Nothing opens, closes or notifies.
   When data returns, the gap is evaluated hour by hour.
```

Episode fields are in S-A: `opened_at`, `state`, kinds seen, `peak_value`, `peak_band`, `last_notified_{at,band,kind}`, `notifications_sent`, `cooldown_until`, `closed_at`, `close_reason`.

---

## 7. D3–D8: the per-user pipeline, and the clock

### 7.1 Two triggers (FR-CLK-1)

- **Data run:** after each ingestion, evaluate every user for every hour that was new or revised.
- **Clock tick:** every hour at `:20`, and at each user's check-in time and quiet-hours end, evaluate every user, even with no new data. This is what writes `NO_DATA` decisions, advances the 24 h timeout, releases held notices and runs check-ins.

Both write `decisions` rows with `trigger = 'data' | 'clock'`. Every hour ends up with a decision for every user: either its reading arrives and the data run evaluates it, or the clock tick writes `NO_DATA` once the newest reading is more than 3 h old (normal publishing delay isn't silence).

**Late hours** older than a user's last evaluated hour are scored and stored, so they shape every later window, but they don't re-run D2–D8 for that past hour: the decision is `no_event · LATE_HOUR_SCORED`. In a sensor outage, all the late hours are newer than the last evaluated one, so they *are* evaluated in order.

### 7.2 Layer order

The first terminal outcome stops the pipeline. Every layer, including stubs, appends a trace entry.

| # | Layer | Passes when | Otherwise → outcome · reason code |
|---|---|---|---|
| 1 | S2/U2 inputs | usable scores for this hour | `no_event` · `NO_DATA` / `NO_BASELINE` / `DQ_*` |
| 2 | **D1 TRIGGER** | kinds evaluated with the user's `k`; near-misses recorded | — (never terminal) |
| 3 | **D2 EPISODE** | the state machine yields a candidate: `opened`, `escalated`, `cleared`, or none | `no_event` · `NO_TRIGGER` / `EPISODE_CONTINUES` / `NO_DATA_TIMEOUT` |
| 4 | **D3 WORTH IT** | `opened`: band ≥ `relevance_floor`. `escalated`: band ≥ last notified band + 1. `cleared`: the episode was notified **and** (lasted ≥ 12 h **or** peaked at USG+ above its typical band) | `suppressed` · `BELOW_RELEVANCE` / `DEDUP_SAME_BAND` / `RECOVERY_NOT_WORTH_SAYING` |
| 5 | **D4 PACE** | time since this episode's last notice ≥ the current gap. The gap starts at 6 h and **doubles with each notice in the same episode** (6 → 12 → 24 h), resetting when the episode closes. Severe escalations skip the wait. | `suppressed` · `COOLDOWN` |
| 6 | **D5 ARBITRATE** *(stub)* | the best candidate this hour for this user, by priority: escalated > opened > cleared > check-in | `suppressed` · `ARBITRATED_OUT` |
| 7 | **D6 RESPOND** *(stub)* | response = `notify` | — |
| 8 | **D7 BUDGET** *(stub)* | fewer than `budget.max_per_day` (3) non-severe notices sent to this user today (local day, all episodes). Severe is never over budget. | `suppressed` · `DAILY_BUDGET` |
| 9 | **D8 TIMING** | outside quiet hours, **or** band ≥ `breakthrough_band`, **or** this is a check-in | `held` · `QUIET_HOURS_HELD` |
| 10 | A1 COMPOSE → A2 DELIVER *(stub)* | message composed (§9) and written to the feed | `sent` · `SENT_*` |

### 7.3 Check-in and held notices (D8)

- **Check-in** (`check_in.cron`, optional; clock-triggered). It evaluates the last 8 h, and speaks only if all three hold: band ≥ `relevance_floor`; `ewma ≥ 1.0` or band above `typical_band`; and no notice sent in the last 6 h. Otherwise `no_event · CHECKIN_QUIET`.
- **The check-in wins over quiet hours.** It's the user's explicit "talk to me now", so D8 passes it even inside the quiet window. Any notices held for that user are **absorbed** into the check-in message (`HELD_RELEASED` on each), and the check-in still counts toward the budget.
- **Release at quiet-hours end.** If anything is still held, all of it collapses into **one** notice about the current state. That notice goes back through D3–D7 at release time. If the episode closed overnight without ever being notified, nothing is sent (`HELD_EXPIRED`).

---

## 8. User rule format

Declarative JSON in `user_rules.rules`, versioned, with `source` = `default | user | learned`. Every field is optional, and missing fields fall back to defaults.

```json
{
  "location":        { "station_id": 4588 },
  "pollutants":      ["pm25"],
  "sensitivity":     "high",
  "relevance_floor": "moderate",
  "alert_band":      "unhealthy",
  "quiet_hours":     { "start": "22:00", "end": "07:00", "breakthrough_band": "very_unhealthy" },
  "check_in":        { "cron": "30 6 * * *" },
  "pace":            { "base_gap_hours": 6 },
  "budget":          { "max_per_day": 3 }
}
```

| Field | Default | Layer |
|---|---|---|
| `location` | required in v1 (one station) | S3 (stub) |
| `sensitivity` | `default` (k = 1.0); `low` 1.25, `high` 0.75 | D1 |
| `relevance_floor` | `moderate` | D2, D3 |
| `alert_band` | `very_unhealthy`; `unhealthy` for `sensitivity: high` | D1 floor |
| `quiet_hours` | `22:00–07:00`, breakthrough at `very_unhealthy`; station local time | D8 |
| `check_in.cron` | none; 5-field cron in station local time, parsed by APScheduler's `CronTrigger.from_crontab` (live and replay) | D8 |
| `pace.base_gap_hours` | 6, doubling within an episode | D4 |
| `budget.max_per_day` | 3 non-severe | D7 |

Validation: unknown fields are rejected, bands must be valid EPA band names, and the cron must parse. Invalid rules fall back to the previous version with `RULES_INVALID`.

**Extension path (not v1).** New rule inputs, such as movement or home-system state, become new typed fields read by D1 or D8. Free-form conditions, if ever needed, use an `extra_conditions` block in the `business-rules` `all/any` JSON shape, evaluated by the `rule-engine` package (S-B §3). L2 ADAPT writes a new version with `source: learned`.

---

## 9. A1 COMPOSE contract (FR-MSG)

The pipeline hands A1 a **structured insight**, never raw data:

```json
{
  "kind": "opened | escalated | cleared | check_in | released_after_quiet_hours",
  "event_kind": "spike | climb | elevated | floor",
  "city": "Delhi", "local_time": "2026-10-18T08:00+05:30",
  "now": { "pm25": 142, "band": "very_unhealthy", "aqi": 203 },
  "typical_for_this_hour": { "pm25": 48, "band": "usg" },
  "episode": { "started": "since 2am", "hours": 6, "peak": { "pm25": 151, "at": "6am" } },
  "absorbed_held": [ { "kind": "opened", "at": "01:00" } ],
  "history_facts": ["worst since 13 Oct", "third bad morning this week"],
  "trend": { "direction": "rising", "per_hour": 9.5 },
  "user": { "name": "Arjun", "persona": { "habits": ["morning run 06:30"], "conditions": [] } },
  "action_candidates": ["skip the outdoor run", "keep windows closed", "wear an N95 if you go out"]
}
```

- **History facts** are computed deterministically: "worst since `<date>`", "Nth bad day this week", "back to normal after N hours/days", "first time this month". At least one is required for spike, climb, elevated and cleared notices.
- **Wording by event kind:** spike → "jumped sharply"; climb → "getting worse since …"; elevated → "stuck above normal for …"; floor → "has crossed into …".
- **One next action** comes from a fixed catalogue keyed by `(kind, band, persona habits, local time of day)`.
- **Generator:** an LLM writes the sentence from this JSON. The output is validated: ≤ 220 characters, mentions exactly one action from the candidates, cites only numbers and dates present in the input. On failure or without an API key, a **template fallback** composes from the same facts. `notifications.generator` records which one ran.

---

## 10. RECORD vocabulary (FR-OBS)

`outcome` ∈ `sent | held | suppressed | no_event`. `trigger` ∈ `data | clock`.

Reason codes by layer:
- **inputs:** `NO_DATA`, `NO_BASELINE`, `DQ_INVALID`, `DQ_LOW_COVERAGE`, `DQ_STUCK`, `DQ_SUSPECT`, `LATE_HOUR_SCORED`
- **D2:** `NO_TRIGGER`, `EPISODE_CONTINUES`, `NO_DATA_TIMEOUT`
- **D3:** `BELOW_RELEVANCE`, `DEDUP_SAME_BAND`, `RECOVERY_NOT_WORTH_SAYING`
- **D4:** `COOLDOWN`
- **D5:** `ARBITRATED_OUT`
- **D7:** `DAILY_BUDGET`
- **D8:** `QUIET_HOURS_HELD`, `HELD_RELEASED`, `HELD_EXPIRED`, `CHECKIN_QUIET`
- **rules:** `RULES_INVALID`
- **sent:** `SENT_OPENED`, `SENT_ESCALATED`, `SENT_CLEARED`, `SENT_CHECK_IN`, `SENT_SEVERE_BYPASS`

Each `trace` entry has the form `{layer, passed, reason_code, inputs, values}`, for example `{layer: "D4", passed: false, reason_code: "COOLDOWN", values: {last_sent: "...", gap_h: 12, elapsed_h: 7.5}}`. Stubs write entries too, e.g. `{layer: "D5", passed: true, values: {candidates: 1}}`. The decision viewer renders traces as plain sentences.

---

## 11. Calibration on the 90-day sample (2026-10-18)

A throwaway replay of the earlier rule version (before climb required a rising slope, and without quiet hours or the check-in). Default user, k = 1.0:

| Station | Episodes / 90 d | Notices per week | Open / escalate / clear | Median episode |
|---|---|---|---|---|
| Helsinki | 10 | 1.5 | 10 / 0 / 8 | 24 h |
| Los Angeles | 14 | 2.1 | 14 / 0 / 11 | 18 h |
| Bengaluru | 15 | 2.4 | 15 / 2 / 12 | 19 h |
| Dubai | 16 | 2.4 | 16 / 2 / 12 | 27 h |
| Delhi (low-cost) | 20 | 3.5 | 20 / 6 / 17 | 18 h |
| Delhi (AirNow reference, fixture) | 20 | 3.3 | — | 9 h |
| Mumbai (glitch fixture) | 11 | 2.7 | — | 12 h |

Sensitive users (k = 0.75) got 1.7–4.3 notices a week. Lessons baked into this spec:
1. CUSUM must reset after signalling. Otherwise episodes never close (Bengaluru stayed open for 20 days).
2. "Cleared" must require the typical band. Otherwise "back to normal" goes out while the air is still unhealthy.
3. The elevated bar at `h = 5` was too eager; `h = 8` plus the recovery-worthiness rule took Delhi from 5.8 to 3.5 a week.
4. 53% of the old "trend" hours were flat or falling, which is why climb now requires a rising slope.
5. Delhi's low-cost sensor and its reference monitor give near-identical rates, so the baseline-relative design absorbs sensor bias.

**To re-measure with the harness:** the climb slope gate and the check-in will shift these numbers. The regression guard in QA.csv (≤ 4 a week per station for the default user) must still hold.

---

## 12. Evaluation harness labels (FR-EVAL-3)

- **Reference labels:** `ruptures` PELT (l2 cost on `y`) over the full sample marks change points. An "interesting moment" is an upward change point whose new segment mean is ≥ 1 band above the previous one, or ≥ 2× the previous mean, and lasts ≥ 3 h. Hand labels add known events (e.g. Helsinki's 24 Aug smoke) and mark Mumbai's glitches as **negatives**.
- **Caught** = a `sent` or `held` decision within 6 h after the moment starts. **Missed** = none. **False alarm** = a sent `opened` notice with no labelled moment within ±6 h. Glitch fixtures must produce zero notices.
- **Report:** per station and persona: caught, missed, false alarms, notices per week, median time-to-notify, and the near-misses closest to each missed moment.

---

## 13. Parameter table

| Parameter | Value | Layer |
|---|---|---|
| Baseline window / min history | 14 days / 72 h | U1 |
| MAD floor (log1p units) | 0.15 | U1 |
| Low coverage / glitch | < 75% / 3× both neighbours and +20 µg/m³ | S2 |
| Gap reset / no-data | > 3 h | S2 |
| Spike | z ≥ 3.5·k in 2 of 3 h | D1 |
| Climb | EWMA (λ 0.3) > 1.26·k for 3 h, and slope_6h > 0.01 | D1 |
| Elevated | CUSUM (k_ref 0.5) > 8·k, needs EWMA ≥ 0.5, reset after firing | D1 |
| Floor | NowCast ≥ alert_band in 2 of 3 h, below it 6 h earlier | D1 |
| Calm hour / close | EWMA < 0.5, no trigger, band ≤ typical; 4 consecutive | D1, D2 |
| Flap window | 6 h | D2 |
| No-data timeout | 24 h, quiet close | D2 |
| Clearing worth saying | ≥ 12 h, or peak USG+ above typical | D3 |
| Pace | 6 h base, doubling within an episode, severe skips | D4 |
| Arbitration priority | escalated > opened > cleared > check-in | D5 |
| Budget | 3 non-severe per local day | D7 |
| Quiet hours | 22:00–07:00, breakthrough at Very Unhealthy; check-in wins | D8 |
| Check-in window / gap | last 8 h / no notice in last 6 h | D8 |
| Sensitivity k | 1.25 / 1.0 / 0.75 | D1 |
