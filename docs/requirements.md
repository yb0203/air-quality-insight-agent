# Requirements — Proactive Health Insight Agent

Status: draft for review · 2026-10-18 · Owner: Yashvi Bansal

This document turns the Orange Invest take-home brief ("Proactive Air Quality Insight Agent") into a product vision plus a v1 scope. Every requirement in the brief has an ID here and a row in the traceability table (section 9), so nothing gets missed. Detailed specs are listed in section 10.

This document is the **spec**: what to build and why. **How each requirement is verified** lives in [QA.csv](QA.csv): one row per test case, with `requirement_ids` tracing back to the IDs here and the brief (B1–B6, BX1–2, S1–5). Every requirement ID in this document has at least one test case. When a requirement changes, update its rows in QA.csv in the same change.

---

## 1. Why this exists

People care about their environment and health signals, but they don't want to check a number every hour. They want something that watches for them and speaks up, unprompted, only when it's actually worth knowing. It should say what changed, why it matters to them, and the one thing to do about it.

The measure of success is restraint as much as detection. A nudge that's late, wrong, or repeated costs trust. A system that stays quiet when nothing has meaningfully changed earns it.

### What this submission should demonstrate

Two things at once, and the requirements are organised to show both:

- **Systems thinking with a long horizon.** The ultimate product (section 2) is much broader than air quality. v1 is built on seams (section 4), so new signals, triggers and actions slot in without a rewrite.
- **Tactical agility.** v1 ships every requirement in the brief, each with exactly one real implementation behind each seam. Nothing is built speculatively.

---

## 2. Ultimate goal (long-term vision)

A proactive personal health agent that watches signals about a person's environment and body, decides on its own when something matters, and acts on it, from a simple heads-up up to taking an action on their behalf.

| Dimension | v1 | Later |
|---|---|---|
| **Signals: external** | Air quality (OpenAQ) | Pollen, UV, heat index, weather |
| **Signals: internal** | none | Heart rate, sleep, activity from wearables |
| **Triggers / rule inputs** | Schedule (cron-style), geo-location, air quality parameters | Movement (gyroscope/accelerometer), home systems (purifier, thermostat, sensors) |
| **Actions** | Notification | Set an alarm, send SOS emails to contacts, control home devices |
| **Configuration** | Smart defaults ("on its own" criteria), tunable per user | Self-learning adjustments based on how the user responds |

---

## 3. Goals, non-goals, anti-goals

### Goals (v1)
- G1. Meet every core requirement in the brief, traceably.
- G2. Detection that is learned from each station's own history, not fixed thresholds.
- G3. Notifications a real person would want to get: rare, specific, contextual, actionable.
- G4. Every decision, including the decision *not* to notify, is explainable after the fact.
- G5. Clear extension seams so the long-term vision reads as a credible next step, not a slide.

### Non-goals (v1)
- Internal health signals, non-notification actions, movement/home triggers.
- Self-learning config adjustments (v1 only *records* user responses; see FR-FB).
- Polished frontend, authentication, multi-tenancy (brief explicitly excludes these).
- Real push delivery infrastructure (APNs/FCM) or any external channel; v1 notifications are stored, served by API and exported (section 8).

### Anti-goals (would be a failure even if it technically works)
- A v1 stuffed with half-built plugin frameworks, registries, or abstractions with one caller each "for the future". That undercuts the agility story.
- A clever single script with no path forward. That undercuts the systems story.
- Notifications that read like status reports ("AQI is now 142") or templates with numbers swapped in.
- A detector that is a fixed threshold dressed up as a model.
- Nagging: repeated, near-identical messages about the same episode.

---

## 4. System shape and extension seams

The pipeline, conceptually:

```
Signal source ──> Reading store ──> Detector ──> Rule evaluation ──> Episode & dedup state ──> Message composer ──> Action / channel
   (OpenAQ)        (history)       (learned)    (user rules +        (what's been said,       (natural language)     (notification)
                                                 defaults)            cooldowns)
                         └──────────────────────── Decision log (every step, every outcome) ─────────────────────────┘
                                                                                     Feedback capture <── user response
```

Seams are where the long-term vision plugs in. In v1 each has **exactly one** implementation. The seam is a clear boundary in the code, not a plugin framework.

| Seam | v1 implementation | How the future plugs in |
|---|---|---|
| Signal source | OpenAQ hourly poller | Pollen API, wearable heart-rate stream: same "readings over time per subject" shape |
| Detector | Learned anomaly / change-point model per station | Same contract for any time series (e.g. resting heart rate) |
| Rule input | Schedule, geo, air quality params | Movement, home-system state become new rule conditions |
| Action | Notification | Alarm, SOS email, device control behind the same "act on a decision" boundary |
| Config source | Defaults + per-user overrides | Learned adjustments write to the same config layer |

---

## 5. Users, cities and how they configure

- **Cities/stations:** 4–5 distinct cities (the brief counts cities, so never two stations in one city), each with one primary OpenAQ station, deliberately mixed between low-pollution and naturally high-pollution or dusty regions, so baseline sensitivity (FR-SENS) is visibly exercised. Final picks depend on data availability (spec S-A).
- **Users:** a few hardcoded users per city with different sensitivities and habits (e.g. an asthmatic morning runner in a clean city vs. a commuter in a dusty one). No auth.
- **Configuration:** via config file and/or API. No settings UI is required. Every user works correctly with zero configuration, on default "on its own" criteria.

---

## 6. Functional requirements (v1)

IDs in brackets map to the brief (section 9).

### FR-ING — Ingestion [B1]
- FR-ING-1. Poll OpenAQ every hour for each tracked station and store every reading with full history.
- FR-ING-2. Ingestion is idempotent: re-polling or overlapping windows never duplicates readings.
- FR-ING-3. Tolerate missing, late and out-of-order readings. Gaps are recorded as gaps, not silently interpolated.
- FR-ING-3a. Store both when a reading was *measured* and when it was *ingested*, so replay can reproduce exactly what the system knew at each moment (see FR-EVAL-5).
- FR-ING-4. Derive an AQI from pollutant concentrations (OpenAQ reports concentrations, not AQI). The AQI standard and pollutant set are decided in spec S-A and documented.
- FR-ING-5. Backfill: on first run, load enough history (e.g. several days to weeks) so baselines exist from day one.
- FR-ING-6. Runs unattended ("always on"). A missed or failed poll is logged and recovered on the next run.

### FR-DET — Insight / trigger detection [B2]
- FR-DET-1. **Primary detection is a simple learned anomaly / change-point model on recent history**, fitted per station. Fixed thresholds may act only as guard rails (e.g. severity floors), never as the primary detector.
- FR-DET-2. Detect a **sustained trend**: the level has been climbing over the last N hours.
- FR-DET-3. Detect a **sudden spike**: a sharp jump versus the station's recent baseline.
- FR-DET-4. Detect a **return to normal** after a bad period.
- FR-DET-5. **False positives:** suppress single-reading blips, sensor glitches and data-quality artifacts (e.g. require persistence or confirmation, gate on data quality, apply hysteresis between "enter" and "exit" states).
- FR-DET-6. **Missed triggers** (core, not dependent on the bonus harness). The live system must actively reduce misses, not just measure them:
  - catch slow-burn rises that never cross a per-hour bar (accumulated drift over a longer window);
  - re-evaluate a station when late or back-filled readings arrive, not only on the newest hour;
  - after a polling gap, evaluate the whole gap rather than only the latest reading;
  - log near-misses (scores just below the bar) so they can be reviewed in the decision log.
  The evaluation harness (FR-EVAL) then *measures* the remaining misses.
- FR-DET-7. The model choice and parameters are decided in the rule engine spec (S-C), informed by research (S-B).

### FR-SENS — Per-city and per-user sensitivity [B5]
- FR-SENS-1. "Unusual" is defined relative to each station's own learned baseline, so a clean city has a lower bar than a naturally dusty one by construction.
- FR-SENS-2. Each user can tighten or loosen sensitivity on top of the station baseline (e.g. a health-sensitive user hears about smaller deviations).
- FR-SENS-3. Absolute health-risk levels still matter: a reading that is "normal for Delhi" but unhealthy in absolute terms must not be silently ignored. How baseline-relative and absolute severity combine is decided in S-C.

### FR-RULE — User notification rules [user scope; supports B3, B5]
Rules let a user shape *when and about what* the agent speaks. They filter and tune the detector's output. They never replace it.

- FR-RULE-1. **Defaults:** every user has sensible default rules, so the agent works on its own judgment with zero configuration.
- FR-RULE-2. **Schedule rules (cron-style):**
  - Quiet hours. Non-urgent insights detected during quiet hours are held and delivered when quiet hours end. Severe events can break through.
  - Optional daily check-in time (e.g. 06:30 before a morning run). The agent compares overnight levels and the current trend against the station's normal for that hour, and speaks only if today is shaping up meaningfully worse than usual. No forecast source in v1. It is not a fixed daily report.
- FR-RULE-3. **Geo rules:** which location(s) a user cares about (home city/station, possibly more than one). Resolved to the nearest tracked station(s).
- FR-RULE-4. **Air quality parameter rules:** which pollutant(s) or index matter to the user, sensitivity level, and optional absolute floors.
- FR-RULE-5. Rules are declarative data (config), not code, so they can later be edited by a UI or by the self-learning layer.
- FR-RULE-6. Every rule evaluation result (passed, held, suppressed, and why) is written to the decision log.
- FR-RULE-7. **The rule engine must be thought through well.** Its logic, rule format, evaluation order and conflict handling are specified in S-C, after researching industry monitoring/alerting rule engines and open-source libraries (S-B).

### FR-DEDUP — Deduplication, rate limiting, cooldown [B3, BX1]
- FR-DEDUP-1. Track **episodes** per user per location: a bad period has a start, an evolution, and an end.
- FR-DEDUP-2. Persist what has already been said in each episode. Six straight bad hours must not produce six identical notifications.
- FR-DEDUP-3. Speak again only on a **meaningful change**, e.g. escalation to a worse severity band, a new kind of event (a spike on top of a trend), or recovery. The exact definition of "meaningful" is decided in S-C.
- FR-DEDUP-4. **Decay / cooldown (bonus):** even after a legitimate re-trigger, enforce a cooldown so the user isn't nagged. The cooldown can relax or decay over time and is overridable by severe escalation.
- FR-DEDUP-5. State survives restarts.

### FR-MSG — Message generation [B4]
- FR-MSG-1. Each notification is a short, natural-language message a real phone notification would show.
- FR-MSG-2. It references **relevant past context** whenever the history supports it, which for trend, spike and recovery events is always (e.g. "since this morning", "worst since Tuesday", "back to normal after two rough days"). A message without past context is the exception and the decision log says why.
- FR-MSG-3. It includes **exactly one clear next action** (e.g. skip the outdoor run, close windows, a good window to go outside now).
- FR-MSG-4. No raw JSON, no templated "AQI is now 142", no pure status updates.
- FR-MSG-5. The composer receives a structured insight (event type, magnitudes, context facts, user profile) and must not invent facts not in that input.
- FR-MSG-6. Generation approach (LLM, templates, or LLM with a deterministic fallback) is a design decision, recorded in the architecture note. If an LLM is used, the system must still produce a valid message when the LLM is unavailable.

### FR-OBS — Observability [B6]
- FR-OBS-1. A **decision log** records, per evaluation: timestamp, user, station, input readings window, detector outputs/scores, rules applied and their results, dedup/cooldown state, final decision (sent / held / suppressed / no event) and reason, and the message if sent.
- FR-OBS-2. Suppressed and held decisions are logged as fully as sent ones, so a *missing* nudge can be debugged as easily as a bad one.
- FR-OBS-3. An internal endpoint and/or simple view to browse decisions by user, station and time, and drill into the data that triggered each one.
- FR-OBS-4. Notification history per user can be exported (also a submission deliverable, S5).

### FR-FB — Feedback capture [user scope; enables future self-learning]
- FR-FB-1. Record how a user responds to each notification (e.g. dismissed, acted, "not useful"), via an API endpoint or the demo UI.
- FR-FB-2. v1 stores feedback and shows it in the decision log. It does not adjust config. Learning from it is a later phase.

### FR-EVAL — Evaluation harness [BX2]
- FR-EVAL-1. Replay historical OpenAQ data through the full pipeline (detector → rules → dedup → decision) on a simulated clock.
- FR-EVAL-2. Report "interesting moments" caught vs. missed, plus false alarms and notification volume per user.
- FR-EVAL-3. How "interesting moments" are labelled (hand labels, a reference rule, or both) is decided in S-C.
- FR-EVAL-4. To make this nearly free, the pipeline never reads wall-clock "now" directly; time is injected.
- FR-EVAL-5. Replay is "as known at the time": at each simulated hour it sees only readings ingested by then, so replayed decisions match what the live system would have done.

### FR-DEMO — Concept demo UI [optional]
- FR-DEMO-1. Optional Next.js front end hosted on Vercel, only to show the concept in the demo: users' notification feeds, the decision log, and replay. Not a product UI.

---

## 7. Non-functional requirements

- NFR-1. **Always on:** hourly cadence runs unattended; failures are visible in logs and self-recover.
- NFR-2. **Explainable:** any notification, or absence of one, can be explained from stored data alone.
- NFR-3. **Deterministic replay:** given the same readings and config, the pipeline makes the same decisions (except LLM wording, if used).
- NFR-4. **Restart-safe:** all state (readings, baselines, episodes, cooldowns, decisions) is persisted.
- NFR-5. **Secrets** (OpenAQ API key, any LLM key) come from environment variables.

---

## 8. Constraints and decisions so far

| Decision | Made by | Notes |
|---|---|---|
| Core service in Python | Yashvi | FastAPI likely (matches the JD's named stack); final in the design |
| Optional Next.js demo UI on Vercel | Yashvi | Concept demo only |
| v1 signal = air quality only, via OpenAQ | Yashvi / brief | OpenAQ v3 requires a free API key |
| v1 action = notification only | Yashvi | |
| v1 rule inputs = schedule, geo, air quality params, with defaults | Yashvi | |
| Schedule rule = quiet hours + optional daily check-in | Yashvi (confirmed proposal) | |
| Self-learning = record feedback only in v1 | Proposed by Claude | Confirm in review |
| Rules are filters/dials on a learned detector, never a replacement | Proposed by Claude | Needed to satisfy B2's "learned model" requirement |
| Config via file/API, no settings UI | Proposed by Claude | Brief excludes frontend |
| Deadline: built within the current working session | Yashvi | Drives the cut order below |
| Cut order if time runs short: Next.js demo first, then the daily check-in, then cooldown decay. The replay harness stays | Proposed by Claude, accepted | The harness is the proof that detection works |
| Hosting: one small hosted Python process that really polls hourly, plus a managed database. No queue or Redis in v1 | Proposed by Claude, accepted | Live history for the demo; anti-goal on premature infra |
| A recorded OpenAQ data sample ships in the repo so replay runs without an API key | Proposed by Claude, accepted | Reviewers can run it cold |
| Daily check-in uses no forecast: overnight levels and the current trend vs. the station's normal for that hour | Proposed by Claude, accepted | Forecasts become a later signal source |
| v1 delivery = notifications stored, served by API and exported as history. No external channel | Claude's call | Resolves Q1; email/Telegram is a later action |
| One location per user in v1; the rule format allows a list | Claude's call | Resolves Q2 |
| Severe events break through quiet hours | Claude's call | Resolves Q3; "severe" defined in S-C |
| 4–5 distinct cities, one primary station each | Claude's call | Brief counts cities |
| Readings carry measured and ingested timestamps; replay is "as known" | Claude's call | Makes replay faithful to live; small schema cost |
| Missed-trigger handling is live (drift, late data, gaps), not only via the harness | Claude's call | B2d is core; the harness is a bonus |

---

## 9. Traceability to the brief

Test cases for each row: filter [QA.csv](QA.csv) by `requirement_ids`.

| ID | Brief requirement | Covered by |
|---|---|---|
| B1 | Ingestion: hourly pull for chosen stations, stored with history | FR-ING-1…6 |
| B2a | Sustained trend | FR-DET-2 |
| B2b | Sudden spike vs. recent baseline | FR-DET-3 |
| B2c | Return to normal after a bad period | FR-DET-4 |
| B2d | False positives and missed triggers | FR-DET-5, FR-DET-6, FR-EVAL |
| B2e | Primary detection = simple learned anomaly/change-point model | FR-DET-1, FR-DET-7 |
| B3 | Dedup / rate limiting; remember what's been said; speak on meaningful change | FR-DEDUP-1…3, FR-DEDUP-5 |
| B4 | Natural-language message, past context, one clear next action, not a status update | FR-MSG-1…6 |
| B5 | Multiple cities/users with different baseline sensitivities | FR-SENS-1…3, FR-RULE-4, section 5 |
| B6 | Observability: what fired, when, why, what data | FR-OBS-1…4 |
| — | 4–5 cities/stations, OpenAQ, hourly | section 5, FR-ING-1 |
| — | Not in focus: frontend, auth, multi-tenancy | section 3 non-goals |
| BX1 | Bonus: decay/cooldown | FR-DEDUP-4 |
| BX2 | Bonus: replay evaluation harness, caught vs. missed | FR-EVAL-1…4 |
| S1 | Deliverable: GitHub repository | yb0203/air-quality-insight-agent |
| S2 | Deliverable: recorded demo video | FR-DEMO (optional) supports it |
| S3 | Deliverable: decision / architecture note | written after specs S-A…S-C |
| S4 | Deliverable: transcript of coding tools / AI used | export Claude Code session transcripts |
| S5 | Deliverable: conversation / notification history | FR-OBS-4 |

---

## 10. Specs to follow (in order)

1. **S-A — OpenAQ API and data schema.** Explore the v3 API, pick 4–5 stations with good hourly coverage across clean and dusty regions, decide the AQI standard and pollutants, and define the storage schema (readings, stations, users, rules, episodes, decisions, feedback).
2. **S-B — Rule engine research.** Survey how industry monitoring and alerting systems handle rules, state, dedup and silencing (e.g. Prometheus Alertmanager, Grafana alerting, Datadog monitors, PagerDuty event rules), plus open-source rule engines and anomaly/change-point libraries, for inspiration.
3. **S-C — Rule engine and detection spec.** The final logic: detector model, event types, the user rule format, evaluation order, severity bands, episode state machine, the definition of "meaningful change", cooldown/decay, and labelling for the evaluation harness.

Then the architecture/design note and an implementation plan.

---

## 11. Open questions

None blocking. Q1 (delivery channel), Q2 (locations per user) and Q3 (quiet-hours breakthrough) were resolved as defaults in section 8 and can be overridden.
