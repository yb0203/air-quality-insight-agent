# How the agent decides: layers, diagrams and an audit

Status: for discussion · 2026-10-18

This document explains the design in [requirements.md](requirements.md) and the specs ([S-A](specs/S-A-openaq-and-schema.md), [S-B](specs/S-B-rule-engine-research.md), [S-C](specs/S-C-rule-engine-spec.md)) at **two scopes**:

- **Max scope**, the ultimate goal: a proactive personal health agent that watches many signals (air, pollen, weather, heart rate, sleep, movement, the home), decides when something matters, and responds, from a message up to calling for help.
- **Min scope**, the demo goal: air quality in five cities, notifications only, every requirement in the brief met.

Both scopes use **the same layers**. The min scope is the max scope with some layers reduced to a one-rule stub or left out. That's what makes the demo a real first slice and not a throwaway.

The audit (section 9) asks four things at both scopes. Is each layer **standard** (how industry solves this kind of problem)? Is each **necessary** (something breaks without it)? Are they **sufficient** together (nothing falls through)? Are they **MECE**, meaning mutually exclusive (no two answer the same question) and collectively exhaustive (every question has an owner)?

Seven findings follow in section 10. **None has been applied to the specs yet.**

---

## 1. Max scope: the ultimate goal

Eighteen layers in five planes. Each layer answers **one question** for **one unit of work**: a data source, a signal stream, a person, a story (episode), or a response.

```
 MAX SCOPE: the ultimate goal
 +================================================================================+
 | PLANE        UNIT OF WORK   LAYER          THE ONE QUESTION IT ANSWERS         |
 +================================================================================+
 | SENSE        per source     S1 INGEST      Did we get the data?                 |
 |                             S2 VALIDATE    Can we trust it?                     |
 |                             S3 RESOLVE     Whose is it, where does it apply,    |
 |                                            and may we use it? (consent)         |
 +--------------------------------------------------------------------------------+
 | UNDERSTAND   per stream     U1 LEARN       What is normal for this stream,      |
 |                                            here, at this time?                  |
 |                             U2 SCORE       How unusual? How harmful?            |
 |              per person     U3 FUSE        What does it mean alongside their    |
 |                                            other signals and context?           |
 +--------------------------------------------------------------------------------+
 | DECIDE       per story      D1 TRIGGER     Is this an event for this person,    |
 |                                            and what kind?                       |
 |                             D2 EPISODE     A new story, or the same story?      |
 |                             D3 WORTH IT    Is there anything new in this story? |
 |                             D4 PACE        Too soon since this story last spoke?|
 |              per person     D5 ARBITRATE   Which candidate wins right now?      |
 |                             D6 RESPOND     Tell them, set an alarm, call for    |
 |                                            help, or adjust the home?            |
 |                             D7 BUDGET      Can we afford their attention today? |
 |                             D8 TIMING      Is now the right moment?             |
 +--------------------------------------------------------------------------------+
 | ACT          per response   A1 COMPOSE     How do we say it?                    |
 |                             A2 DELIVER     Did it reach them / did it happen?   |
 +--------------------------------------------------------------------------------+
 | LEARN        per person     L1 FEEDBACK    How did they respond?                |
 |                             L2 ADAPT       Should their settings change?        |
 +================================================================================+
 | CROSS-CUTTING  RECORD   every answer, including "stay quiet"                    |
 |                REPLAY   any past hour, exactly as it was known then             |
 |                GUARD    consent, and safety limits on high-stakes actions       |
 |                OPERATE  is the pipeline itself healthy (freshness, failures)?   |
 +================================================================================+
```

**Why DECIDE is split in two.** The first four layers judge **one story at a time**: "the air in Delhi is getting worse". The last four judge **the person as a whole**, across every story competing for their attention: Delhi air, plus high pollen, plus a heart-rate oddity. Mixing those two scopes is where alert fatigue comes from, so they are separate layers.

**Why this order.** RESPOND comes before BUDGET and TIMING because the type of response changes both. A call for help ignores quiet hours and is never "over budget". A routine heads-up respects both.

### What max scope looks like in action (illustrative)

```
  Fusion: three ordinary-looking signals become one clear message

   air (U2):    PM2.5 above normal, Unhealthy ----+
   body (U2):   heart rate 15% above their usual -+--> U3 FUSE: "exerting in bad air"
   motion (S1): running for the last 20 min ------+          |
                                                             v
                       D1..D8 --> A1: "The air's turned unhealthy and your heart rate's
                                       up. Maybe walk the rest of the way home."

  High-stakes response: GUARD sits in front of every irreversible action

   asthma profile + Hazardous air + no response to 2 messages in 30 min
       --> D6 RESPOND proposes "SOS to emergency contact"
       --> GUARD: is the consent on file? Is the action rate-limited? Does it need a
                  one-tap confirmation, or is there a timeout?
       --> A2 DELIVER: send it, and record the receipt
```

---

## 2. Min scope: the demo goal

The same eighteen layers. Each is **REAL** (built properly), a **STUB** (one rule, named in code and in the decision trace, so the seam is visible) or **NONE** (left out entirely, because nothing needs it yet).

```
 MIN SCOPE: the demo goal (air quality, 5 cities, notifications only)
 +==================================================================================+
 | LAYER          STATUS  WHAT IT IS IN THE DEMO                          BRIEF      |
 +==================================================================================+
 | S1 INGEST      REAL    OpenAQ hourly, trailing 24h window, backfill   B1         |
 | S2 VALIDATE    REAL    invalid / low coverage / stuck / glitch checks B2d (FP)   |
 | S3 RESOLVE     STUB    hardcoded user -> one station; no consent step  B5         |
 +----------------------------------------------------------------------------------+
 | U1 LEARN       REAL    14-day hour-of-day median/MAD per station       B2e, B5    |
 | U2 SCORE       REAL    z, EWMA, CUSUM, 6h slope, NowCast -> EPA band   B2e        |
 | U3 FUSE        NONE    one signal, so nothing to fuse                  -          |
 +----------------------------------------------------------------------------------+
 | D1 TRIGGER     REAL    spike / climb / elevated / clearing / floor,    B2a-c, B5  |
 |                        scaled by the user's sensitivity                           |
 | D2 EPISODE     REAL    state machine, hysteresis, flap guard           B3         |
 | D3 WORTH IT    REAL    relevance floor, one-band escalation,           B3         |
 |                        recovery only after a bad period                           |
 | D4 PACE        REAL    6h gap, doubling within a story                 BX1        |
 | D5 ARBITRATE   STUB    at most 1 message per user per hour, by         B3         |
 |                        precedence: worse > opened > cleared > check-in            |
 | D6 RESPOND     STUB    always "notify"                                 -          |
 | D7 BUDGET      STUB    at most 3 non-severe messages per user per day  B3         |
 | D8 TIMING      REAL    quiet hours (hold and release), morning check-in  (scope)  |
 +----------------------------------------------------------------------------------+
 | A1 COMPOSE     REAL    LLM from structured facts + template fallback   B4         |
 | A2 DELIVER     STUB    "delivered" = visible in the API / feed / export  S5       |
 +----------------------------------------------------------------------------------+
 | L1 FEEDBACK    REAL*   records acted / dismissed / not useful          (scope)    |
 | L2 ADAPT       STUB    nothing changes; rules are versioned so it can    (scope)  |
 |                        later write a "learned" version                            |
 +==================================================================================+
 | RECORD  REAL   decision log for every user x hour, with reasons        B6         |
 | REPLAY  REAL   replay harness, as-known data, caught vs missed         BX2        |
 | GUARD   NONE   no high-stakes actions yet                              -          |
 | OPERATE REAL*  ingestion_runs: freshness, failures, rate limits        NFR-1      |
 +==================================================================================+
   REAL* = real but minimal.   11 real · 6 stubs · 1 none, plus 3 of 4 cross-cutting.
```

**Why stubs and not nothing?** A stub costs one rule, but it puts the layer's name in the code and in every decision trace (`ARBITRATE: 1 candidate, passed`). When pollen or heart rate arrive, the layer gets filled in, not invented. That isn't a half-built framework: each stub is a single, tested rule with no abstraction behind it.

**Why the stubs are necessary even in the demo:**
- ARBITRATE: a check-in and an episode message can land in the same hour.
- BUDGET: a jumpy day with back-to-back episodes could otherwise produce four or five messages.
- DELIVER: the brief asks for a notification history (S5).

---

## 3. Where each layer comes from (is it standard?)

The design is **two standard industry pipelines joined at the episode**. The upper half is a **monitoring and alerting** pipeline. The lower half is a **notification orchestration** pipeline, the kind consumer apps use to avoid fatiguing people. Clinical early-warning systems (e.g. the NHS NEWS2 score) follow the same shape: combine vital signs into a score, then apply an escalation policy.

```
   MONITORING & ALERTING                                NOTIFICATION ORCHESTRATION
   (Prometheus, Datadog, Grafana)                       (Braze, Airship, LinkedIn, Duolingo)

   collect -> validate -> baseline -> score -> rule       eligibility -> dedup -> rank -> cap
     S1        S2          U1        U2      D1              D3          D3/D4    D5     D7
                                               \           /
                                                 EPISODE  (incident / dedup_key in PagerDuty)
                                                   D2
                                               /           \
                                     escalation policy        send-time / quiet hours -> render -> deliver -> learn
                                         D6                        D8                    A1        A2       L1/L2
```

| Layer | Industry equivalent | Our twist |
|---|---|---|
| S1 INGEST | scrape / collector | trailing-window re-fetch catches late data |
| S2 VALIDATE | data-quality checks, data contracts | OpenAQ doesn't flag glitches, so we must |
| S3 RESOLVE | identity resolution, consent management | — |
| U1 LEARN | anomaly baselines (Datadog "robust", seasonal) | per hour of day, robust statistics, recomputed each hour |
| U2 SCORE | anomaly score + an absolute standard | two scores: unusual (learned) and harmful (EPA) |
| U3 FUSE | sensor fusion, complex event processing, early-warning scores | — |
| D1 TRIGGER | alert rule with `for` (Prometheus) | shape labels: spike / climb / elevated |
| D2 EPISODE | incident with a dedup key (PagerDuty), alert grouping | per user, with a flap guard |
| D3 WORTH IT | Alertmanager "notify only on change" | recovery only after a genuinely bad period |
| D4 PACE | renotify interval (Datadog), repeat interval | doubles within a story (decay) |
| D5 ARBITRATE | inhibition (Alertmanager), notification ranking | precedence list in v1 |
| D6 RESPOND | escalation policy (PagerDuty), action routing | — |
| D7 BUDGET | frequency capping (Braze, Airship) | — |
| D8 TIMING | quiet hours, send-time optimisation | **hold and release**, not drop |
| A1 COMPOSE | templates / rendering | LLM bound to verified facts, template fallback |
| A2 DELIVER | push providers with receipts | — |
| L1 / L2 | engagement tracking; bandit-style tuning (Duolingo) | learned changes become a visible, reversible rules version |
| RECORD | audit log / incident timeline | logs every *silence* too |
| REPLAY | backtesting | as-known replay, so replay equals live |

**Verdict: every layer has a standard counterpart.** The deliberate departures are holding instead of dropping, recomputing instead of accumulating, and logging silences as fully as messages.

---

## 4. Two clocks drive it, not one

```
   OpenAQ                                                                 
     |   every hour at :20, fetch the last 24h per sensor                 
     v                                                                    
  [S1..S2] --new or revised hours--> [U1..U2] --scores--> [D1..D8] --> [A1..A2] --> feed
                                                              ^
   CLOCK -----------------------------------------------------+
     every hour, plus each user's check-in time and the end of quiet hours:
       - marks sensors without fresh data as NO_DATA (missed-trigger safety)
       - releases notices held overnight
       - runs the morning check-in
```

---

## 5. Two questions, never one (U2 SCORE)

```
                              Is it HARMFUL? (EPA band, same scale everywhere)
                               no (Good)                   yes (Moderate or worse)
                         +---------------------------+---------------------------------+
   Is it UNUSUAL         | Stay quiet.               | TELL THEM.                       |
   for this place?   yes | "Helsinki went 3 -> 5."   | "Worse than a normal Delhi       |
   (learned per          | Odd, but harmless.        |  morning, and unhealthy."        |
   station, per hour)    | -> BELOW_RELEVANCE        |  -> the normal path              |
                         +---------------------------+---------------------------------+
                      no | Nothing to say.           | Mostly quiet. Delhi sits in      |
                         |                           | "unhealthy for sensitive groups" |
                         |                           | for weeks; saying so hourly is   |
                         |                           | noise. Two exceptions:           |
                         |                           | - crossing UP into the user's    |
                         |                           |   alert band (absolute floor)    |
                         |                           | - the morning check-in, when     |
                         |                           |   today is worse than usual      |
                         +---------------------------+---------------------------------+
```

This is how a low-pollution city gets a lower bar for "unusual" (brief B5) without anyone being told about harmless changes.

---

## 6. Event shapes (D1 TRIGGER)

```
  how far above normal (z)
   ^
   |        SPIKE                 CLIMB                    ELEVATED
   |          |                       ___/                 
   |          |\                  ___/                   ______________
   |          | \            ____/                  ____/              
   |   _______|  \______  __/                    __/                   
   |                                                                     
   +-----------------------------------------------------------------------> hours
      a sharp jump vs the      rising hour after         stuck above normal
      last few hours           hour, for 6 hours         for many hours, but
                                                         not rising
      fastest: fires on        EWMA above the bar        cumulative excess
      2 of 3 hours             AND a positive slope      (CUSUM) crosses a bar

      CLEARING: an open episode gets 4 calm hours AND is back to the station's usual band
      FLOOR:    crossing UP into the user's alert band, whatever is "normal" there
```

**One label per event** (mutually exclusive), by precedence: spike > climb > elevated. **Every upward departure is covered** (collectively exhaustive): it's fast, rising or flat-and-high. Falling-but-still-high is the same episode continuing, not a new event.

---

## 7. One bad period is one story (D2 EPISODE)

```
                 event fires AND the air is at least Moderate
     NORMAL  --------------------------------------------->  ACTIVE  <-----+
       ^                                                        |          |
       |                                            a calm hour |          | event again, or
       |  6h pass after close                                   v          | a non-calm hour
       |                                                   RECOVERING -----+
     CLOSED  <------------- 4 calm hours in a row --------------+
       |   ^
       |   +---- 24h with NO DATA: close silently (NO_DATA_TIMEOUT)          [proposed, F6]
       |
       +-- event within 6h of closing --> the SAME episode reopens (anti-flapping)

     NO DATA (under 24h): the episode is frozen. Nothing opens, closes or notifies.
                          When data returns, the missing hours are replayed in order.
```

---

## 8. Restraint, in order: story first, then person

```
   candidate message (opened / got worse / cleared / check-in)
        |
   ---- per STORY -------------------------------------------------------------------
        v
   [D3 WORTH IT]   anything NEW in this story?
        |            opened: yes. got worse: only if a full band worse than last told.
        |            cleared: only after a genuinely bad period (12h+, or peaked well above usual)
        |   no --> suppressed  DEDUP_SAME_BAND / RECOVERY_NOT_WORTH_SAYING / BELOW_RELEVANCE
        v
   [D4 PACE]       too soon since this story last spoke?   6h, then 12h, then 24h
        |   no --> suppressed  COOLDOWN                 (severe air skips the queue)
        |
   ---- per PERSON ------------------------------------------------------------------
        v
   [D5 ARBITRATE]  several candidates this hour? keep the most important one
        |   lost --> suppressed  ARBITRATED_OUT
        v
   [D6 RESPOND]    which response? (demo: always notify)
        v
   [D7 BUDGET]     over today's attention budget?   3 non-severe per day
        |   yes --> suppressed  DAILY_BUDGET        (severe air is never over budget)
        v
   [D8 TIMING]     a good moment?   quiet hours hold until morning unless severe;
        |                           the check-in is an explicit "talk to me now"
        |   no --> held  QUIET_HOURS_HELD  (released later as ONE combined message)
        v
   [A1 COMPOSE] -> [A2 DELIVER] -> sent
                     ...and every step above is written to the decision log, pass or fail.
```

**Why PACE and BUDGET are not the same thing.** PACE asks "too soon *in this story*?" and resets when the story ends. BUDGET asks "how much of *this person's* attention have we spent today, across *every* story?" In the demo they rarely disagree. With several signals they disagree constantly: three different stories can each be well paced and still add up to too much for one person.

---

## 9. A night in Delhi, hour by hour (illustrative)

**The numbers are made up but follow the spec.** Arjun lives in Delhi and runs at 06:30. He has default sensitivity, quiet hours 22:00–07:00, and a check-in at 06:30.

```
 local  band (NowCast)   station says (U)            Arjun's pipeline (D)                     outcome
 -----  ---------------  --------------------------  ---------------------------------------  -------------------
 22:00  USG              normal for a Delhi night    no event                                 no_event
 23:00  USG              rising                      climb needs 3h above the bar             no_event
 00:00  USG              rising                      not yet                                  no_event
 01:00  Unhealthy        CLIMB fires                 episode OPENS; worth it; pace ok;        held
                                                     budget ok; but quiet hours               QUIET_HOURS_HELD
 02:00  Unhealthy        still climbing              same story, same band                    suppressed
                                                                                              DEDUP_SAME_BAND
 03:00  Unhealthy (peak) flat                        same story                               suppressed
 04:00  Unhealthy        easing                      same story                               suppressed
 06:30  Unhealthy        well above a usual morning  CHECK-IN: worse than usual, and a held   SENT (one message)
                                                     notice is waiting -> merged into one
          "Air got worse overnight from about 1am and is still unhealthy, well above a normal
           Delhi morning. Maybe skip the outdoor run today and try an indoor workout."
 07:00  Unhealthy        -                           quiet hours end; nothing left to release  -
 10:00  Unhealthy        -                           same story, same band                     suppressed
 14:00  USG              calm hour 1                 episode RECOVERING                        no_event
 17:00  USG              calm hour 4                 episode CLOSES; it lasted 16h, so worth   SENT
                                                     saying; 10.5h since last, so pace ok
          "Delhi's air is back to its usual level after a rough 16 hours. If you missed your
           run this morning, the evening looks fine for it."
```

Two messages in about 20 hours, each with context and one action. "Why didn't I hear at 2am?" has a logged answer: quiet hours, then nothing new to say.

---

## 10. The audit at both scopes

### 10.1 Standard?
Yes: every layer has an industry counterpart (section 3). The design is two standard pipelines joined at the episode.

### 10.2 Necessary?

| Layer | Min scope | Max scope | Evidence (from the 90-day calibration unless noted) |
|---|---|---|---|
| S1 INGEST | needed | needed | — |
| S2 VALIDATE | needed | needed | Mumbai: 8 one-hour readings of 784–982 µg/m³, none flagged by OpenAQ, all caught |
| S3 RESOLVE | stub | needed (many users, devices, consent) | — |
| U1 LEARN | needed | needed | station medians span 4.2 to 45.9 µg/m³ (11×); one threshold can't serve them all |
| U2 SCORE | needed | needed | — |
| U3 FUSE | **not needed** | needed (heart rate + air + movement) | — |
| D1 TRIGGER | needed | needed | per-user sensitivity changes volume: 1.5–3.5 vs 1.7–4.3 messages a week |
| D2 EPISODE | needed | needed | without proper closing, Bengaluru stayed "open" 20 days (pass 1) |
| D3 WORTH IT | needed | needed | without it, "back to normal" went out while the air was still unhealthy (pass 2) |
| D4 PACE | needed | needed | bonus BX1 |
| D5 ARBITRATE | stub (check-in vs episode in the same hour) | needed (many stories) | — |
| D6 RESPOND | stub | needed (alarm, SOS, home) | — |
| D7 BUDGET | stub (back-to-back episodes) | needed (many stories) | — |
| D8 TIMING | needed | needed | — |
| A1 COMPOSE | needed | needed | brief B4 |
| A2 DELIVER | stub | needed (channels, receipts) | — |
| L1 FEEDBACK | minimal | needed | — |
| L2 ADAPT | stub | needed (self-learning) | — |
| RECORD / REPLAY | needed | needed | all calibration depended on replay; B6, BX2 |
| GUARD | not needed | **needed before any SOS or home action** | — |
| OPERATE | minimal | needed | Bengaluru's government stations silent for about 108h right now |

**Verdict:** every layer is necessary at max scope. At min scope, eleven are necessary as real layers (one minimal), six as one-rule stubs, and only U3 FUSE and GUARD can be left out.

### 10.3 Sufficient?

Min scope against the brief:

| Brief | Owner | Status |
|---|---|---|
| B1 ingestion with history | S1 | ✓ |
| B2a sustained trend ("climbing") | U2 + D1 | ✓ **after F1** |
| B2b sudden spike | U2 + D1 | ✓ |
| B2c return to normal | D1 + D2 + D3 | ✓ |
| B2d false positives | S2 + D1 (confirmation) + D2 (hysteresis) | ✓ |
| B2d missed triggers | D1 (elevated), S1 (late data), CLOCK (silence) | ✓ **after F5** |
| B2e learned model is primary | U1 + U2 | ✓ |
| B3 dedup, meaningful change | D2 + D3 (+ D5, D7) | ✓ |
| B4 natural message, context, one action | A1 | ✓ |
| B5 per-city / per-user sensitivity | U1 + D1 + section 5 | ✓ |
| B6 observability | RECORD | ✓ |
| BX1 cooldown / decay | D4 | ✓ |
| BX2 replay evaluation | REPLAY | ✓ |
| (implied) a sensor dies mid-episode | D2 | ✓ **after F6** |

Max scope against the vision:

| Vision element | Owner |
|---|---|
| Pollen, UV, weather | S1 + U1 + U2 (same stream contract) |
| Heart rate, sleep, activity | S1 + S3 (whose device) + U1 + U2 |
| Combined meaning ("exerting in bad air") | U3 |
| Movement and home-system triggers | S1 (as context) + U3 + D1 |
| Alarm, SOS email, device control | D6 + A2 + GUARD |
| Many signals, one person, no fatigue | D5 + D7 |
| Self-learning settings | L1 + L2, bounded by GUARD |

**Verdict:** sufficient at both scopes, once F1, F5 and F6 land.

### 10.4 MECE?

**Mutually exclusive.** Two layers may share a question only if they work on different units of work. They may share a unit only if they ask different questions.

| Pair that looks alike | Why they are distinct |
|---|---|
| D4 PACE vs D7 BUDGET | same question family, different unit: one story vs the whole person |
| D3 WORTH IT vs D5 ARBITRATE | within one story ("is this new?") vs across stories ("which wins?") |
| U3 FUSE vs D1 TRIGGER | FUSE changes what the signals *mean*; TRIGGER decides whether that meaning *is an event* |
| D6 RESPOND vs D8 TIMING | *what* response vs *when*; severity bypasses are a timing policy per response type |
| L2 ADAPT vs user rules | ADAPT writes a new rules version; GUARD bounds it; the rules format is shared |
| climb vs elevated (inside D1) | **overlap today** (F1): 53% of "trend" hours aren't rising |
| station scoring vs per-user triggering | **tangled today** (F4): user sensitivity is applied inside station detection |

**Collectively exhaustive.** Every question in the system now has an owner, including the previously unowned ones: who notices a silent sensor (CLOCK, F5), who ends a dead sensor's episode (D2, F6), and who decides check-in vs quiet hours (D8, F7).

---

## 11. Findings and proposed fixes

| # | Finding | Proposed fix | Layer | Needs your call? |
|---|---|---|---|---|
| **F1** | "Trend" checks *high*, not *rising*: 53% of trend hours were flat or falling; duplicates drift; misreads brief B2a | Kinds become **spike / climb / elevated** (+ clearing, floor). Climb = EWMA bar **and** a positive 6h slope. Elevated = CUSUM. One label by precedence. Re-calibrate. | D1 | no: needed for the brief |
| **F2** | The inhibition stage looked redundant | **Keep, rename ARBITRATE.** Standard layer, needed at max scope. In the demo it's one rule: one message per user per hour, by precedence. | D5 | no |
| **F3** | The daily cap looked redundant with cooldown | **Keep, rename BUDGET** (per person, across stories). Distinct from PACE by unit of work. Demo: 3 non-severe a day, with a test that it rarely fires on the sample. | D7 | no |
| **F4** | User sensitivity is tangled into station detection | The station layer stores sensitivity-free **scores**. The user layer applies sensitivity and floors in TRIGGER. The `detections` table becomes `station_scores`. | U2 / D1 | no |
| **F5** | Clock-driven work has no named trigger | The **clock tick** becomes a first-class trigger: every user gets a decision every hour, even when no data arrived. | CLOCK | no |
| **F6** | A dead sensor's episode never ends | After 24h of NO_DATA, close silently (`NO_DATA_TIMEOUT`). | D2 | **yes**: also tell the user the sensor went quiet? |
| **F7** | Check-in inside quiet hours is undefined | The check-in is an explicit "talk to me now": it wins and absorbs held messages. | D8 | **yes** (the proposal seems natural) |

---

## 12. Key decisions in one place

| Decision | Why | Rejected alternative | Source |
|---|---|---|---|
| Same layers at both scopes; the demo uses stubs, not shortcuts | the demo is the first slice of the product, not a throwaway | a demo-only script | this doc |
| DECIDE split into per-story and per-person halves | that split is what prevents fatigue once there are many signals | one combined restraint step | §1, §8 |
| Learn "normal" per station **and per hour of day** | rush hours and nights differ | one average; fixed thresholds | S-C §3 |
| Log scale, robust statistics (median/MAD) | a doubling means the same everywhere; past spikes don't distort "normal" | mean / standard deviation | S-B §4 |
| Recompute every hour from stored data | replay equals live; late data is handled for free | incremental detector state | S-C §1 |
| EPA bands with NowCast for "harmful" | built for hourly use; one scale for every city | India's 24h index | S-B §2 |
| Hand-rolled rule pipeline | holding, cooldown and episodes aren't covered by any rule library | rule-engine, CEL, ZEN, durable_rules | S-B §3 |
| Hold overnight, don't drop | a dropped warning is a missed trigger | Alertmanager-style silences | S-C §6 |
| Five cities, clean to dusty, one station each | shows per-city sensitivity; the brief counts cities | several stations per city | S-A §2 |
| PM2.5 only in the demo | the only pollutant all five stations measure | multi-pollutant with gaps | S-A §2 |
| Ship a 90-day sample | anyone can replay without an API key | live-only | S-A §6 |
