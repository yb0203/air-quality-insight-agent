# How the agent decides

Status: **closed** · 2026-10-18 · This document is the design source of truth. Its decisions have been carried into [requirements.md](requirements.md), the specs ([S-A](specs/S-A-openaq-and-schema.md), [S-B](specs/S-B-rule-engine-research.md), [S-C](specs/S-C-rule-engine-spec.md)) and [QA.csv](QA.csv).

---

## 1. Purpose

The agent watches signals about a person's surroundings and body, decides on its own when something is worth knowing, and responds. It speaks rarely, says what changed and why it matters to *this* person, and offers one thing to do. Restraint matters as much as detection.

The design is described at two scopes that share **one set of layers**:

- **Full scope**, the ultimate goal: many signals (air, pollen, weather, heart rate, sleep, movement, the home) and many responses (a message, an alarm, a call for help, adjusting the home), with settings that learn.
- **Demo scope**, what we build now: air quality (PM2.5) in five cities, notifications only, every requirement in the brief met.

The demo isn't a separate, simpler design. It's the full design with some layers reduced to a single rule or left out. Sections 2–4 give the big picture. Sections 5–9 walk through the layers. Section 10 follows one night end to end, and section 11 records the decisions.

---

## 2. The layers at full scope

Eighteen layers in five planes. Each answers **one question** for **one unit of work**: a data source, a signal stream, a person, a story (episode) or a response.

```
 FULL SCOPE: the ultimate goal
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

Three structural choices shape everything else:

- **Station work is shared, person work is not.** SENSE and UNDERSTAND produce facts about a place that are the same for everyone: how unusual the air is, and how harmful. Everything personal (sensitivity, schedule, history) starts at D1. A person's settings never change a station's scores.
- **DECIDE has two halves.** D1–D4 judge **one story at a time** ("Delhi's air is getting worse"). D5–D8 judge **the person as a whole**, across every story competing for their attention: Delhi air, high pollen, an odd heart-rate reading. Keeping those apart is what stops alert fatigue once there are many signals.
- **What comes before when.** D6 RESPOND comes before D7 BUDGET and D8 TIMING, because the kind of response changes both. A call for help ignores quiet hours and is never "over budget". A routine heads-up respects both.

What full scope looks like in practice (illustrative):

```
  Fusion: three ordinary-looking signals become one clear message

   air (U2):    PM2.5 above normal, Unhealthy ----+
   body (U2):   heart rate 15% above their usual -+--> U3 FUSE: "exerting in bad air"
   motion (S1): running for the last 20 min ------+          |
                                                             v
                       D1..D8 --> A1: "The air's turned unhealthy and your heart rate's
                                       up. Maybe walk the rest of the way home."

  High-stakes response: GUARD sits in front of every irreversible action

   asthma profile + Hazardous air + no reply to 2 messages in 30 min
       --> D6 RESPOND proposes "SOS to emergency contact"
       --> GUARD: is consent on file? Is the action rate-limited? Does it need a
                  one-tap confirmation, or a timeout?
       --> A2 DELIVER: send it, and record the receipt
```

---

## 3. The layers at demo scope

The same eighteen layers. Each one is **REAL** (built properly), a **STUB** (a single rule, named in code and in every decision trace, so the seam is visible) or **NONE** (left out, because nothing needs it yet).

```
 DEMO SCOPE: air quality, 5 cities, notifications only
 +==================================================================================+
 | LAYER          STATUS  WHAT IT IS IN THE DEMO                          BRIEF      |
 +==================================================================================+
 | S1 INGEST      REAL    OpenAQ hourly, trailing 24h window, backfill   B1         |
 | S2 VALIDATE    REAL    invalid / low coverage / stuck / glitch checks B2d        |
 | S3 RESOLVE     STUB    hardcoded user -> one station; no consent step  B5         |
 +----------------------------------------------------------------------------------+
 | U1 LEARN       REAL    14-day hour-of-day baseline per station         B2e, B5    |
 | U2 SCORE       REAL    unusual: z, EWMA, CUSUM, slope                  B2e        |
 |                        harmful: NowCast -> EPA band                               |
 | U3 FUSE        NONE    one signal, so nothing to fuse                  -          |
 +----------------------------------------------------------------------------------+
 | D1 TRIGGER     REAL    spike / climb / elevated / clearing / floor,    B2a-c, B5  |
 |                        scaled by the person's sensitivity                         |
 | D2 EPISODE     REAL    lifecycle, hysteresis, flap guard, timeout      B3         |
 | D3 WORTH IT    REAL    relevance floor, one-band escalation,           B3         |
 |                        "cleared" only after a bad period                          |
 | D4 PACE        REAL    6h gap, doubling within a story                 BX1        |
 | D5 ARBITRATE   STUB    one message per person per hour, by priority    B3         |
 | D6 RESPOND     STUB    always "notify"                                 -          |
 | D7 BUDGET      STUB    at most 3 non-severe messages per person a day  B3         |
 | D8 TIMING      REAL    quiet hours (hold and release), morning check-in -         |
 +----------------------------------------------------------------------------------+
 | A1 COMPOSE     REAL    LLM from verified facts, template fallback      B4         |
 | A2 DELIVER     STUB    "delivered" = visible in the feed and export    S5         |
 +----------------------------------------------------------------------------------+
 | L1 FEEDBACK    REAL*   records acted / dismissed / not useful          -          |
 | L2 ADAPT       STUB    no changes; rules are versioned for later       -          |
 +==================================================================================+
 | RECORD  REAL   decision log for every person x hour, with reasons      B6         |
 | REPLAY  REAL   replay harness on as-known data, caught vs missed       BX2        |
 | GUARD   NONE   no high-stakes actions yet                              -          |
 | OPERATE REAL*  ingestion runs: freshness, failures, rate limits        -          |
 +==================================================================================+
   REAL* = real but minimal.   11 real · 6 stubs · 1 none, plus 3 of 4 cross-cutting.
```

How each stub or empty layer grows into its full form:

| Layer | Demo | Full scope |
|---|---|---|
| S3 RESOLVE | a fixed person-to-station mapping | identity, devices, locations, consent per signal |
| U3 FUSE | none | combines streams and context into one meaning ("exerting in bad air") |
| D5 ARBITRATE | one message per hour, by a fixed priority | ranks competing stories by urgency and relevance |
| D6 RESPOND | always notify | chooses between a message, an alarm, an SOS, a home action, with escalation |
| D7 BUDGET | 3 non-severe a day | an attention budget shared by all signals, tuned per person |
| A2 DELIVER | written to the feed | push, email, SMS, device APIs, with retries and receipts |
| L2 ADAPT | none; rules are versioned | proposes a new "learned" rules version, bounded by GUARD and reversible |
| GUARD | none | consent, confirmations and rate limits before any irreversible action |

A stub costs one rule, but it puts the layer in the code and in every trace (`ARBITRATE: 1 candidate, kept`). Later, the layer gets filled in, not invented. Three stubs are needed even in the demo. A check-in and an episode message can land in the same hour (ARBITRATE). A jumpy day with back-to-back episodes could otherwise stack up messages (BUDGET). And the brief asks for a notification history (DELIVER).

---

## 4. Two clocks drive it

Most work happens when new data arrives. Some must happen when **no** data arrives: noticing a silent sensor, releasing messages held overnight, running the morning check-in. So every hour, every person gets a decision, whichever clock fired.

```
   OpenAQ
     |   every hour at :20, fetch the last 24h per sensor
     v
  [S1..S2] --new or revised hours--> [U1..U2] --scores--> [D1..D8] --> [A1..A2] --> feed
                                                              ^
   CLOCK -----------------------------------------------------+
     every hour, plus each person's check-in time and the end of their quiet hours:
       - marks sensors without fresh data as NO_DATA
       - releases messages held overnight
       - runs the morning check-in
```

---

## 5. Sense: getting data we can trust

**S1 INGEST.** Every hour, for each tracked sensor, fetch the **last 24 hours** and store anything new. Data usually arrives 0.5–2.5 hours late, and sometimes much later. The overlapping window picks up late readings, and the newly filled hours are evaluated as if they had arrived on time. Readings are never overwritten. A changed value is stored as a new version with the time we received it, so we can always ask "what did we know at 3am?". On first run, up to 90 days are backfilled so a baseline exists from day one.

**S2 VALIDATE.** OpenAQ doesn't flag bad readings, so we do.

| Check | Rule | Example from the real data |
|---|---|---|
| Invalid | below 0 or above 1000 µg/m³ | Sydney low-cost sensors: about a third of hours ≤ 0 (not tracked) |
| Low coverage | the hour is less than 75% complete | — |
| Stuck | the same value for 6+ hours | — |
| Glitch | 3× higher than both neighbours and +20 µg/m³ | Mumbai: 75 → **980** → 90 in three hours; 8 such hours in 58 days, none flagged by OpenAQ |

Excluded readings stay visible as evidence. They just don't count. The newest hour can't be fully glitch-checked until the next one arrives. So if it *jumps* more than 3× and by more than 20 µg/m³ over the previous hour, it's treated as a suspected glitch until the next hour either confirms it (still high: real, re-scored as clean) or clears it (fell back: a glitch, and the decision log says so). That costs nothing for spikes, which need two hours of confirmation anyway. Only a severity jump waits one hour, and it stops one bad reading from escalating an open episode straight to "hazardous".

**S3 RESOLVE.** In the demo, each person follows exactly one station. At full scope this layer answers whose device a reading came from, which places a person cares about, and whether we have consent to use each signal.

---

## 6. Understand: what is normal, and what is harmful

**U1 LEARN.** For each station and each hour of the day, the agent learns what's normal from the last 14 days. It works on a log scale, so a doubling means the same thing in Helsinki and in Delhi. It uses the median and median absolute deviation, so last week's smoke doesn't distort "normal". Hours with little history borrow from the station's all-day pattern, and a station needs 72 hours of clean history before it can judge anything. Each station also gets a **typical band**: the official air quality category of its usual level.

```
  what "normal" looks like (90-day medians, µg/m³)

   Helsinki     4.2  |##                                     typical: Good
   Los Angeles 10.0  |#####                                  typical: Moderate
   Bengaluru   20.7  |##########                             typical: Moderate
   Dubai       41.0  |####################                   typical: Unhealthy for Sensitive Groups
   Delhi       45.9  |######################                 typical: Unhealthy for Sensitive Groups
                     +----+----+----+----+----+
                     0   10   20   30   40   50
```

**U2 SCORE.** Two different questions get two different answers, and neither depends on who is asking.
- **How unusual?** How far the latest hour sits from normal for that hour of day (z). That comes with a smoothed version (EWMA), a running total of excess (CUSUM) and the direction of the last 6 hours (slope).
- **How harmful?** The official US EPA category of the hourly-weighted average (NowCast): Good, Moderate, Unhealthy for Sensitive Groups, Unhealthy, Very Unhealthy, Hazardous. Same scale everywhere.

A message needs the right combination of the two:

```
                              Is it HARMFUL? (EPA band, same scale everywhere)
                               no (Good)                   yes (Moderate or worse)
                         +---------------------------+---------------------------------+
   Is it UNUSUAL         | Stay quiet.               | TELL THEM.                       |
   for this place?   yes | "Helsinki went 3 -> 5."   | "Worse than a normal Delhi       |
   (learned per          | Odd, but harmless.        |  morning, and unhealthy."        |
   station, per hour)    |                           |                                  |
                         +---------------------------+---------------------------------+
                      no | Nothing to say.           | Mostly quiet. Delhi sits in      |
                         |                           | "unhealthy for sensitive groups" |
                         |                           | for weeks; saying so hourly is   |
                         |                           | noise. Two exceptions:           |
                         |                           | - crossing UP into the person's  |
                         |                           |   alert band                     |
                         |                           | - the morning check-in, when     |
                         |                           |   today is worse than usual      |
                         +---------------------------+---------------------------------+
```

That's how a clean city gets a lower bar for "unusual" without anyone hearing about harmless changes.

**U3 FUSE** is not in the demo. At full scope it combines a person's streams and context into one meaning before anything is decided.

---

## 7. Decide: from a score to a message, with restraint

### 7.1 D1 TRIGGER: is it an event, and what kind?

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
      a sharp jump vs the      rising, hour after        stuck above normal
      last few hours           hour                      for many hours, but
                                                         not rising
      far above normal in      smoothed level above      running total of excess
      2 of the last 3 hours    the bar for 3 hours       crosses the bar (each hour
                               AND the 6h slope is up    counts at most a spike's
                                                         worth); resets once it fires

      CLEARING   an open episode has 4 calm hours AND is back to the station's typical band
      FLOOR      crossing UP into the person's alert band, whatever is "normal" there
```

- **One label per event**, by priority: spike, then climb, then elevated. The label drives the wording ("jumped sharply", "getting worse since 2am", "stuck above normal all day").
- **Every way of getting worse is covered.** Air goes up fast (spike), keeps rising (climb), or sits high and flat (elevated). Falling-but-still-high isn't a new event. It's the same story continuing.
- **Elevated exists to catch what the others miss.** These are slow build-ups that never look dramatic in any single hour.
- **The person's sensitivity scales every bar.** Sensitive people get bars 25% lower; people who want fewer messages get bars 25% higher. Station scores are unchanged; only the bar moves.

### 7.2 D2 EPISODE: one bad period is one story

```
                 event fires AND the air is at least Moderate
     NORMAL  --------------------------------------------->  ACTIVE  <-----+
       ^                                                        |          |
       |                                            a calm hour |          | event again, or
       |  6h pass after close                                   v          | a non-calm hour
       |                                                   RECOVERING -----+
     CLOSED  <------------- 4 calm hours in a row --------------+
       |   ^
       |   +---- 24h with NO DATA: close quietly, no message (NO_DATA_TIMEOUT)
       |
       +-- event within 6h of closing --> the SAME episode reopens (no "it's getting bad" again)

     NO DATA (under 24h): the episode is frozen. Nothing opens, closes or notifies.
                          When data returns, the missing hours are replayed in order.
```

### 7.3 D3–D8: restraint, story first, then person

```
   candidate (opened / got worse / cleared / check-in)
        |
   ---- per STORY -------------------------------------------------------------------
        v
   [D3 WORTH IT]   anything NEW in this story?
        |            opened: yes, if the air is at least Moderate
        |            got worse: only if a full band worse than last told
        |            cleared: only after a genuinely bad period
        |                     (12h or longer, or peaked above both USG and the usual band)
        |   no --> suppressed  BELOW_RELEVANCE / DEDUP_SAME_BAND / RECOVERY_NOT_WORTH_SAYING
        v
   [D4 PACE]       too soon since this story last spoke?   6h, then 12h, then 24h
        |   no --> suppressed  COOLDOWN                  (severe air skips the wait)
        |
   ---- per PERSON ------------------------------------------------------------------
        v
   [D5 ARBITRATE]  several candidates this hour? keep one:
        |            got worse > opened > cleared > check-in
        |   lost --> suppressed  ARBITRATED_OUT
        v
   [D6 RESPOND]    which response?   (demo: always notify)
        v
   [D7 BUDGET]     over today's attention budget?   3 non-severe a day
        |   yes --> suppressed  DAILY_BUDGET          (severe air is never over budget)
        v
   [D8 TIMING]     a good moment?
        |            quiet hours (22:00-07:00 by default) hold messages until morning,
        |            unless the air is Very Unhealthy or worse
        |            the morning check-in is an explicit "talk to me now": it wins over
        |            quiet hours and absorbs any held messages into one
        |   no --> held  QUIET_HOURS_HELD   (released later as ONE combined message)
        v
   [A1 COMPOSE] -> [A2 DELIVER] -> sent
```

- **PACE and BUDGET are different questions.** PACE asks "too soon *in this story*?" and resets when the story ends. BUDGET asks "how much of *this person's* attention have we spent today, across every story?" With one signal they rarely disagree. With several, three well-paced stories can still add up to too much.
- **Held messages are never just dropped.** At release, everything held for a person becomes **one** message about the current state. It's re-checked against D3–D7 at that moment. If the story ended overnight without ever being told, nothing is sent.
- **The check-in is not a daily report.** At the person's chosen time, it looks at the last 8 hours. It speaks only if the air is at least Moderate and worse than usual for that time, and nothing was sent in the last 6 hours.

**How the numbers were chosen.** Every bar and waiting time above was tuned by replaying 90 days of real data from all five cities. The final replay made 15,345 decisions and sent 251 notices. Default users get 1.6–2.3 event notices a week, plus their optional morning check-ins. Delhi is the busiest as it enters smog season. The replay harness re-measures this whenever a rule changes.

---

## 8. Act: saying it well

**A1 COMPOSE.** The decision layers hand over **verified facts**, never raw data:

```
  { kind: "got worse",  city: "Delhi",  local time: 08:00,
    now: 142 µg/m³, Very Unhealthy,      usual for 8am: 48, USG,
    story: since 2am, 6 hours, peak 151 at 6am,
    history: "worst since 13 Oct", "third bad morning this week",
    person: Arjun, runs at 06:30,
    action options: skip the outdoor run | keep windows closed | wear an N95 outside }
```

- An LLM writes one or two sentences from these facts. A validator then checks the result: short enough for a phone notification, includes exactly one of the offered actions, and cites no number or date that isn't in the facts.
- If the LLM fails the check or isn't available, a template writes the message from the same facts.
- Past context is always included for climb, spike and clearing messages ("since 2am", "worst since Tuesday", "back to normal after two rough days"). It's never a bare status like "AQI is now 142".

**A2 DELIVER.** In the demo, a message is "delivered" when it appears in the person's feed and in the exported history. Real channels come at full scope.

---

## 9. Learn, and what runs across everything

- **L1 FEEDBACK.** A person can mark a message as acted on, dismissed or not useful. In the demo, this is stored and shown next to the decision, and changes nothing.
- **L2 ADAPT.** Settings are stored as numbered versions, and every decision records which version it used. A future learning layer will propose a new "learned" version, never edit silently, so every change is visible and reversible.
- **RECORD.** Every person gets a decision row for every hour, with an outcome (sent, held, suppressed or no event), a reason code and a stage-by-stage trace of the inputs, values and results. "Why didn't I hear about it at 2am?" always has an answer, as complete as "why did I hear about it?"
- **REPLAY.** Nothing in the pipeline reads the real clock, and every hour is recomputed from the readings known at that moment. So replaying the past gives exactly the decisions the live system would have made. Replay is how the rules were tuned, and how caught versus missed moments are measured.
- **GUARD.** Not in the demo. At full scope it stands in front of every irreversible action: consent, confirmation and rate limits.
- **OPERATE.** Every ingestion run is logged with its freshness, failures and remaining rate limit, so the pipeline's own health is visible.

---

## 10. A night in Delhi, hour by hour (illustrative)

The numbers are made up but follow the rules above. Arjun lives in Delhi and runs at 06:30. He has default sensitivity, quiet hours 22:00–07:00, and a check-in at 06:30.

```
 local  band (NowCast)   station layer               Arjun's decision                         outcome
 -----  ---------------  --------------------------  ---------------------------------------  -------------------
 22:00  USG              normal for a Delhi night    no event                                 no event
 23:00  USG              rising                      climb needs 3 hours above the bar        no event
 00:00  USG              rising                      not yet                                  no event
 01:00  Unhealthy        CLIMB                       episode OPENS; worth it; pace, budget    held
                                                     ok; but quiet hours                      QUIET_HOURS_HELD
 02:00  Unhealthy        still climbing              same story, same band                    suppressed
                                                                                              DEDUP_SAME_BAND
 03:00  Unhealthy (peak) flat                        same story                               suppressed
 04:00  Unhealthy        easing                      same story                               suppressed
 06:30  Unhealthy        well above a usual morning  CHECK-IN wins over quiet hours; worse    SENT (one message)
                                                     than usual; the held message merges in
          "Air got worse overnight from about 1am and is still unhealthy, well above a normal
           Delhi morning. Maybe skip the outdoor run today and try an indoor workout."
 07:00  Unhealthy        -                           quiet hours end; nothing left to release  -
 10:00  Unhealthy        -                           same story, same band                     suppressed
 14:00  USG              calm hour 1                 episode RECOVERING                        no event
 17:00  USG              calm hour 4                 episode CLOSES; it lasted 16h, so worth   SENT
                                                     saying; 10.5h since last, pace ok
          "Delhi's air is back to its usual level after a rough 16 hours. If you missed your
           run this morning, the evening looks fine for it."
```

Two messages in about 20 hours, each with context and one action. Every silent hour has a logged reason.

---

## 11. Decision record

| # | Decision | Why | Rejected alternative | Industry lineage |
|---|---|---|---|---|
| 1 | One set of layers for both scopes; the demo uses stubs | the demo is the first slice of the product, not a throwaway | a demo-only script | — |
| 2 | Station scores are shared and never depend on the person | facts about a place are the same for everyone; personal bars move, scores don't | per-person detection | shared metrics, per-route rules (Prometheus, Alertmanager) |
| 3 | DECIDE split into per-story and per-person halves | the split is what prevents fatigue with many signals | one combined restraint step | incident handling (PagerDuty) + notification orchestration (Braze, Airship) |
| 4 | "Normal" per station **and** per hour of day, over 14 days | rush hours and nights differ; seasons drift | one average; fixed thresholds | seasonal anomaly baselines (Datadog) |
| 5 | Log scale with median and MAD | a doubling means the same everywhere; old spikes don't distort normal | mean and standard deviation | robust statistics |
| 6 | "Unusual" and "harmful" are separate scores | a clean city gets a lower bar without harmless alerts | one blended score | anomaly score + a published standard (EPA AQI) |
| 7 | EPA bands with NowCast | built for hourly use; one scale for every city | India's 24-hour index (too slow for hourly nudges) | US EPA / AirNow |
| 8 | Event shapes: spike, climb, elevated (+ clearing, floor), one label each | matches the brief's trend and spike; elevated catches slow build-ups | thresholds only | control charts: EWMA, CUSUM (NIST) |
| 9 | Episodes with hysteresis and a flap guard | one bad period is one story; no on-off-on storms | per-hour alerts with a mute timer | alert states and `for` (Prometheus, Grafana), dedup keys (PagerDuty) |
| 10 | Recompute every hour from stored data | replay equals live; late data handled for free | incremental detector state | backtesting |
| 11 | Hand-rolled decision pipeline | holding, pacing and episodes aren't covered by any rule library | rule-engine, CEL, ZEN, durable_rules | — |
| 12 | Hold overnight and release as one message | a dropped warning is a missed trigger | silences that discard | quiet hours (consumer apps) |
| 13 | Five cities, clean to dusty, one station each | shows per-city sensitivity; the brief counts cities | several stations per city | — |
| 14 | PM2.5 only in the demo | the only pollutant all five stations measure | multi-pollutant with gaps | — |
| 15 | Messages written by an LLM from verified facts, with a template fallback | natural wording without invented facts; works offline | free-form LLM; templates only | — |
| 16 | A 90-day sample ships in the repo | anyone can replay without an API key | live-only | — |
| 17 | A sensor silent for 24h closes its episode quietly, with no message | the story can't be finished honestly without data | telling the person the sensor went quiet | — |
| 18 | The morning check-in wins over quiet hours and absorbs held messages | the person chose that time to hear from us | quiet hours win | — |
| 19 | A late hour older than a person's last evaluated hour is scored, but doesn't rewind their story | re-running old hours would double-count episode changes; the score still shapes every later hour | re-evaluating history in place | — |
| 20 | The clock records "no data" only once the newest reading is over 3 hours old | normal publishing delay (0.5–2.5 h) isn't silence | marking every quiet tick as no data | — |
| 21 | One scheduler (APScheduler) runs both the live schedule and cron parsing for check-ins, also in replay | one source of truth for "when is 06:30 local" | a separate cron library | — |
| 22 | A newest-hour jump is a suspected glitch until the next hour confirms or clears it; each arrival re-checks the hour before | the Mumbai replay showed single glitch hours leaking through severity escalation | evaluating the newest hour as clean | — |
| 23 | Each hour adds at most a spike's worth (z 3.5) to the slow-build running total | one wild hour could otherwise fire "elevated" on its own | an unclipped CUSUM | robust (clipped) CUSUM |
| 24 | The replay counts a moment as caught within 6 hours either side of its onset | an early catch is a good catch (Helsinki smoke was flagged before the hand-labelled start) | after-onset only | — |
| 25 | Volume guard: at most 4 event notices a week, and 5 including morning check-ins | check-ins are opt-in and answer "should I run today?" | one combined cap | — |

Decisions 17 and 18 were confirmed by Yashvi on 2026-10-18, 19–21 with the implementation plan, and 22–25 came out of the 90-day replay during the build.
