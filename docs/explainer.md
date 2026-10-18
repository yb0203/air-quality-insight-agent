# How the agent decides — explained, with an audit of every layer

Status: for discussion · 2026-10-18

This document explains the design in [requirements.md](requirements.md) and the specs ([S-A](specs/S-A-openaq-and-schema.md), [S-B](specs/S-B-rule-engine-research.md), [S-C](specs/S-C-rule-engine-spec.md)) with diagrams. It then audits the layers. Is each one **necessary** (something breaks without it)? Are they **sufficient** together (nothing in the brief falls through)? Are they **MECE**: mutually exclusive (no two layers answer the same question) and collectively exhaustive (every question has an owner)?

The audit found seven issues. They're listed in section 9 with proposed fixes. **None of the fixes has been applied to the specs yet.**

---

## 1. The whole thing in one picture

Every layer answers exactly one question. The first four run once per station and are shared by all users there. The rest run once per user, because people differ in sensitivity, schedule and history.

```
                      +--------------------------------------------------------------+
                      |  1  INGEST     Do we have the data?                          |
  STATION LAYER       |  2  CLEAN      Can we trust this reading?                    |
  once per sensor,    |  3  LEARN      What is normal here, at this hour of day?     |
  shared by everyone  |  4  SCORE      How unusual is it?  How harmful is it?        |
                      +--------------------------------------------------------------+
                      |  5  TRIGGER    Is this an event for THIS person, and what    |
  USER LAYER          |                kind (spike / climb / elevated / clearing)?   |
  once per user       |  6  EPISODE    Is it a new story, or the same story?         |
                      |  7  WORTH IT   Is there something new worth telling?         |
                      |  8  PACE       Is it too soon after the last message?        |
                      |  9  TIMING     Is now a good moment to say it?               |
                      | 10  SAY        How do we say it, with one clear action?      |
                      +--------------------------------------------------------------+
  CROSS-CUTTING       |  RECORD every answer, including "stay quiet"                 |
                      |  REPLAY any past hour exactly as it was known then           |
                      +--------------------------------------------------------------+
```

> This is the **proposed** layering. The current S-C spec differs in two places: it scores and triggers in one combined per-user step (finding F4), and it has an extra "inhibition" stage (finding F2).

---

## 2. Two clocks drive it, not one

Most of the work happens when new data arrives. But some decisions have to happen even when **no** data arrives: noticing a sensor went silent, releasing messages held overnight, and running the morning check-in. So there are two triggers.

```
   OpenAQ                                                               
     |   every hour at :20, fetch the last 24h per sensor               
     v                                                                  
  [1 INGEST] --new or revised hours--> [2..4 STATION] --scores--> [5..10 USER] --> notices
                                                                     ^
   CLOCK ------------------------------------------------------------+
     every hour, plus each user's check-in time and quiet-hours end:
       - marks sensors with no fresh data as NO_DATA
       - releases notices that were held overnight
       - runs the morning check-in
```

> The current spec describes the clock-driven work but never names the clock as a trigger. That's finding F5.

---

## 3. Two questions, never one

"Unusual" and "harmful" are different questions, so they're answered by different layers. Statistics learned per station decide what is **unusual**. The official US EPA air quality bands decide what is **harmful**. A message needs the right combination.

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
                         |                           | for weeks; saying so hourly      |
                         |                           | would be noise. Two exceptions:  |
                         |                           | - crossing UP into the user's    |
                         |                           |   alert band (absolute floor)    |
                         |                           | - the morning check-in, when     |
                         |                           |   today is worse than usual      |
                         +---------------------------+---------------------------------+
```

This one picture is how we satisfy the brief's "a low-pollution city should have a lower bar for unusual" without spamming anyone about harmless changes.

---

## 4. What counts as an event: shapes, not thresholds

The brief asks for a sustained trend, a sudden spike and a return to normal. We also catch a slow build-up that never looks dramatic in any single hour, because that's where triggers get missed.

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
      sharp jump vs the        rising, hour after        stuck above normal
      last few hours           hour, for 6 hours         for many hours, but
                                                         not rising
      fastest: fires on        EWMA above the bar        CUMULATIVE excess
      2 of 3 hours             AND a positive slope      (CUSUM) crosses a bar

      CLEARING: after an episode, 4 calm hours AND back to the station's usual band
```

**Mutually exclusive by precedence.** One hour can match several shapes, so each event gets exactly one label: spike first, then climb, then elevated. That label drives the wording ("jumped sharply" vs "getting worse since 2am" vs "stuck above normal all day").

**Collectively exhaustive.** Any upward departure is fast (spike), rising (climb) or flat-and-high (elevated). Falling-but-still-high isn't a new event. It's the same episode continuing.

> **This is where the audit found the biggest issue (F1).** In the current spec, "trend" only checks that the smoothed level is high. It doesn't check that it's *rising*. On the 90-day sample, **53% of "trend" hours were flat or falling** (Dubai 57%, Bengaluru 61%). So today's "trend" mostly duplicates "drift", and it doesn't match the brief's "climbing for the last N hours". The diagram above shows the proposed fix.

---

## 5. One bad period is one story: the episode

Instead of reacting to every hour, each bad period becomes an **episode** with a beginning, middle and end. This is what makes "six bad hours, one message" possible.

```
                 event fires AND air is at least Moderate
     NORMAL  --------------------------------------------->  ACTIVE  <-----+
       ^                                                        |          |
       |                                            a calm hour |          | event again or
       |  6h pass after close                                   v          | a non-calm hour
       |                                                   RECOVERING -----+
     CLOSED  <------------- 4 calm hours in a row --------------+
       |
       +-- event within 6h of closing --> the SAME episode reopens
                                          (no fresh "it's getting bad" message: anti-flapping)

     NO DATA: the episode is frozen. Nothing opens, closes or notifies.
              When data returns, the missing hours are replayed in order.
```

> The current spec has no way out of a long silence. If a sensor dies mid-episode, the episode stays open forever (finding F6).

---

## 6. Restraint: four different questions, in a fixed order

Once there's a candidate message, it must pass four checks. Each asks a different question, so each has a different fix when it says no.

```
   candidate message (opened / got worse / cleared / check-in)
        |
        v
   [7 WORTH IT]   Is there anything NEW to say?
        |           opened: always new
        |           got worse: only if a full band worse than last told
        |           cleared: only after a genuinely bad period (>= 12h, or peaked well above usual)
        |   no ---> suppressed  DEDUP_SAME_BAND / RECOVERY_NOT_WORTH_SAYING / BELOW_RELEVANCE
        v
   [8 PACE]       Is it too soon after the last message?
        |           gap starts at 6h and doubles within an episode: 6h, 12h, 24h
        |           severe air (Very Unhealthy+) skips the queue
        |   no ---> suppressed  COOLDOWN
        v
   [9 TIMING]     Is now a good moment?
        |           quiet hours (22:00-07:00 default): hold until morning, unless severe
        |   no ---> held  QUIET_HOURS_HELD  (released later as ONE combined message)
        v
   [10 SAY]       compose: what changed + past context + exactly one action
        |
        v
      sent       and every step above is written to the decision log, pass or fail
```

> Today's spec has two more gates: an "inhibition" stage between 7 and 8, and a daily cap inside 8. The audit says both overlap with other layers (findings F2 and F3).

---

## 7. A night in Delhi, hour by hour (illustrative)

A walkthrough of the rules. **The numbers are made up but follow the spec.** Arjun lives in Delhi and runs at 06:30. He has default sensitivity, quiet hours from 22:00 to 07:00, and a check-in at 06:30.

```
 local  band (NowCast)   station layer says          Arjun's pipeline                         outcome
 -----  ---------------  --------------------------  ---------------------------------------  -------------------
 22:00  USG              normal for a Delhi night    no event                                 no_event
 23:00  USG              rising                      climb needs 3h above the bar             no_event
 00:00  USG              rising                      not yet                                  no_event
 01:00  Unhealthy        CLIMB fires                 episode OPENS; worth it; pace ok;        held
                                                     but quiet hours                          QUIET_HOURS_HELD
 02:00  Unhealthy        still climbing              same story, same band                    suppressed
                                                                                              DEDUP_SAME_BAND
 03:00  Unhealthy (peak) flat                        same story                               suppressed
 04:00  Unhealthy        easing                      same story                               suppressed
 06:30  Unhealthy        well above usual morning    CHECK-IN: worse than usual, and a held   SENT (one message)
                                                     notice is waiting -> merge into one
          "Air got worse overnight from about 1am and is still unhealthy, well above a normal
           Delhi morning. Maybe skip the outdoor run today and try an indoor workout."
 07:00  Unhealthy        -                           quiet hours end; nothing left to release  -
 10:00  Unhealthy        -                           same story, same band                     suppressed
 14:00  USG              calm hour 1                 episode RECOVERING                        no_event
 17:00  USG              calm hour 4                 episode CLOSES; it lasted 16h -> worth    SENT
                                                     saying; 10.5h since last -> pace ok
          "Delhi's air is back to its usual level after a rough 16 hours. If you missed your
           run this morning, the evening looks fine for it."
```

Two messages in about 20 hours, both carrying context and one action. Everything else is logged with a reason, so "why didn't I hear about it at 2am?" has an answer: quiet hours, then nothing new to say.

> Walking through this surfaced a gap. **Arjun's check-in (06:30) falls inside his quiet hours (until 07:00).** The current spec doesn't say which wins (finding F7). The walkthrough assumes the proposed fix: the check-in is an explicit "talk to me now", so it wins and absorbs held messages.

---

## 8. The audit: is every layer necessary, sufficient and distinct?

### 8.1 Necessary: what breaks without each layer

| Layer | Question it owns | Without it... | Evidence |
|---|---|---|---|
| 1 Ingest | Do we have the data? | no history, no trend (brief B1) | — |
| 2 Clean | Can we trust it? | sensor glitches become alerts | Mumbai: 8 one-hour readings of 784–982 µg/m³, **none flagged by OpenAQ**, all caught by our glitch check |
| 3 Learn | What's normal here, now? | one threshold for every city: Helsinki never alerts, or Delhi always does | medians range from 4.2 (Helsinki) to 45.9 µg/m³ (Delhi), an 11× spread |
| 4 Score | How unusual, how harmful? | no shared measure for triggers, bands or messages | — |
| 5 Trigger | Event for this person, and which kind? | no per-user sensitivity (brief B5); no spike/climb/elevated distinction (brief B2) | a sensitive user gets 1.7–4.3 messages a week vs 1.5–3.5 for default |
| 6 Episode | New story or same story? | six bad hours, six messages (brief B3) | calibration pass 1: without proper closing, Bengaluru stayed "open" for **20 days** |
| 7 Worth it | Anything new to say? | repeats; "back to normal" while still unhealthy | pass 2 sent recovery notices at "Unhealthy"; recovery-worthiness cut Delhi from 5.8 to 3.5 a week |
| 8 Pace | Too soon? | rapid-fire messages on a jumpy day (bonus BX1) | — |
| 9 Timing | Good moment? | 3am pings for non-urgent news | — |
| 10 Say | How to say it? | JSON or "AQI is now 142" (brief B4) | — |
| Record | Why did we act or not? | a missing nudge can't be debugged (brief B6) | — |
| Replay | What would we have done? | parameters can't be tuned or measured (bonus BX2) | all three calibration passes depended on it |

**Verdict: every proposed layer is necessary.**

### 8.2 Sufficient: does anything in the brief fall through?

| Brief | Owned by | Status |
|---|---|---|
| B1 hourly ingestion with history | 1 | covered |
| B2a sustained trend ("climbing") | 4 + 5 | **covered only after F1** (today "trend" doesn't check climbing) |
| B2b sudden spike | 4 + 5 | covered |
| B2c return to normal | 5 + 6 + 7 | covered |
| B2d false positives | 2 + 6 (confirmation, hysteresis) | covered |
| B2d missed triggers | 5 (elevated/drift), 1 (late data), clock (gaps) | **covered after F5** (the clock must notice silence) |
| B2e learned model is primary | 3 + 4 | covered |
| B3 dedup, speak only on meaningful change | 6 + 7 | covered |
| B4 natural message, context, one action | 10 | covered |
| B5 per-city / per-user sensitivity | 3 + 5 + section 3 above | covered |
| B6 observability | Record | covered |
| BX1 cooldown / decay | 8 | covered |
| BX2 replay evaluation | Replay | covered |
| (implied) sensor dies mid-episode | 6 | **gap → F6** |

### 8.3 Mutually exclusive: do two layers answer the same question?

| Pair | Overlap? | Verdict |
|---|---|---|
| "trend" vs "drift" detectors | **yes**: both mean "elevated", 53% of trend hours aren't rising | fix with F1: climb = rising, elevated = flat-high |
| spike vs trend | partly: spikes almost always co-occur with trend | fine after F1. Precedence gives one label; spike's job is speed and wording. |
| inhibition (S-C stage 6) vs episode + worth-it | **yes**: with one location and one pollutant per user, an episode yields at most one candidate per hour | F2: remove the stage, keep "one message per user per hour" as a rule in SAY |
| daily cap vs doubling cooldown | **mostly**: cooldown already bounds volume (theoretical max ~4 a day across back-to-back episodes, observed 1.5–3.5 a week) | F3: drop the cap, or keep it as a silent safety net (your call) |
| relevance floor vs absolute floor vs "typical band" | no: same scale, three different questions (worth saying a worsening / crossed a hard line / back to usual) | keep |
| quiet hours vs check-in | **yes, at the boundary**: a check-in inside quiet hours is undefined | F7: check-in wins and absorbs held messages |
| station scoring vs per-user triggering | **tangled** today: S-C applies user sensitivity inside detection, but detections are stored per sensor | F4: score once per station (no user knobs); apply each user's thresholds in TRIGGER |

### 8.4 Collectively exhaustive: does every question have an owner?

Gaps: who notices a silent sensor (F5)? Who ends an episode whose sensor died (F6)? Who decides between check-in and quiet hours (F7)? After the fixes, each has an owner.

---

## 9. Findings and proposed fixes

| # | Finding | Proposed fix | Cost | Needs your call? |
|---|---|---|---|---|
| **F1** | "Trend" checks *high*, not *rising*: 53% of trend hours were flat or falling; it duplicates drift and misreads brief B2a | Rename the kinds to **spike / climb / elevated**. Climb = EWMA bar **and** a positive 6h slope. Elevated = CUSUM (today's drift). One label per event by precedence. Re-calibrate with the harness. | small | no: needed to meet the brief |
| **F2** | The inhibition stage is redundant in v1 (one location and one pollutant per user) | Remove stage 6. Add an invariant to SAY: at most one message per user per hour, preferring got-worse > opened > cleared > check-in. Bring it back when users follow several places or pollutants. | removes code | no |
| **F3** | The daily cap overlaps the doubling cooldown | Option A: drop it (fewer knobs, more MECE). Option B: keep it as a silent safety net that should never fire, with a test asserting it doesn't on the sample. | tiny | **yes** |
| **F4** | User sensitivity is applied inside station detection, but detections are stored per station: a layering tangle | The station layer stores sensitivity-free **scores** (z, EWMA, CUSUM, slope, NowCast, band). The user layer applies `k` and floors in TRIGGER and records the result in the decision trace. The `detections` table becomes `station_scores`. | small schema change | no |
| **F5** | The clock-driven work (silence, overnight release, check-ins) has no named trigger | Make the **clock tick** a first-class trigger next to the data tick (section 2). Every hour, every user gets a decision even when no data arrived (NO_DATA). | small | no |
| **F6** | An episode whose sensor dies stays open forever | After 24h of NO_DATA, close the episode **silently** (`NO_DATA_TIMEOUT`, no message). Optionally tell the user the sensor went quiet. | small | **yes**: tell the user or not? |
| **F7** | Check-in time inside quiet hours is undefined | The check-in is an explicit "talk to me now". It wins, and absorbs any held messages into one. | tiny | **yes**, but the proposal seems natural |

---

## 10. Key decisions in one place

| Decision | Why | Rejected alternative | Source |
|---|---|---|---|
| Learn "normal" per station **and per hour of day** | rush hours and nights differ; a flat average fires every evening in Delhi | one 24h average; fixed thresholds | S-C §3 |
| Work in log scale with robust statistics (median/MAD) | a doubling means the same thing in clean and dirty cities; past spikes don't distort normal | mean/standard deviation (spike-sensitive) | S-B §4 |
| Recompute everything each hour from stored data | replay equals live; late data is handled for free | incremental detector state | S-C §1 |
| EPA bands with NowCast for "harmful" | built for hourly use; one scale for every city | India's 24h index (too slow for hourly nudges) | S-B §2 |
| Hand-rolled rule pipeline | the hard parts (holding, cooldown, episodes) aren't covered by any rule library | rule-engine, CEL, ZEN, durable_rules | S-B §3 |
| Episodes with hysteresis and a flap guard | industry-proven way to stop alert storms (Prometheus, Grafana, PagerDuty) | per-hour alerts with a mute timer | S-B §1 |
| Hold overnight, don't drop | a dropped warning is a missed trigger; held ones merge into one morning message | Alertmanager-style silences that discard | S-C §6 |
| Five cities from clean to dusty, one station each | shows per-city sensitivity; the brief counts cities | several stations per city | S-A §2 |
| PM2.5 only in v1 | the only pollutant all five stations measure | multi-pollutant with gaps | S-A §2 |
| Ship a 90-day sample in the repo | anyone can replay without an API key | live-only | S-A §6 |
