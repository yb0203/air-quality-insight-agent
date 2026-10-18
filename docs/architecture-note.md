# Architecture and decision note

A short summary for reviewers. The full design, with diagrams of every layer, is in [explainer.md](explainer.md). The exact logic and parameters are in [specs/S-C-rule-engine-spec.md](specs/S-C-rule-engine-spec.md).

## What it is

A Python service that watches hourly PM2.5 from OpenAQ for five cities: Helsinki, Los Angeles, Bengaluru, Dubai and Delhi. It decides on its own when something is worth telling a person, and writes a short message with past context and one action. Every decision, including every silence, is logged with a reason and a layer-by-layer trace.

## Shape

Eighteen layers in five planes, the same at full product scope and in this demo ([explainer §2–3](explainer.md)):

- **Sense:** ingest, validate, resolve. Per source.
- **Understand:** learn what's normal, score how unusual and how harmful, fuse. Shared per station. A person's settings never change a station's scores.
- **Decide:** first per story (trigger, episode, worth it, pace), then per person (arbitrate, respond, budget, timing).
- **Act:** compose, deliver.
- **Learn:** feedback, adapt.
- **Across everything:** record, replay, guard, operate.

In the demo, 11 layers are real, 6 are one-rule stubs that keep the seams visible, and 1 (fuse) is left out.

Code: `src/aqagent/` has one module per layer, plus `runner.py`, which wires the two triggers (new data, and the hourly clock). The demo watch app is separate and decoupled, in `apps/watch_demo/`.

## Key decisions and trade-offs

1. **"Unusual" and "harmful" are separate questions.** Each station learns its own hour-of-day normal (median and MAD on log PM2.5, 14 days). The US EPA bands, via NowCast, decide what's harmful. A clean city gets a lower bar without anyone being told about harmless changes.
2. **Event shapes, not thresholds.** Spike (2 of 3 hours), climb (EWMA plus a rising slope), elevated (a capped CUSUM for slow build-ups), clearing and an absolute floor. One label per event.
3. **One bad period is one story.** Episodes have hysteresis and a flap guard. Restraint runs story first (worth it, pace doubling 6, 12, 24 hours), then person (arbitration, a daily attention budget, quiet hours that *hold* and release rather than drop, a morning check-in that wins over quiet hours).
4. **Recompute, don't accumulate.** Every hour is re-derived from the readings known at that moment, and time is injected. So replay equals live, and late data needs no special handling.
5. **Hand-rolled decision pipeline.** No rule library models holding, pacing or episodes. Each layer is a small pure function that writes its reason code.
6. **Messages from verified facts.** An LLM (Claude Haiku, if a key is set) writes from a structured insight. A validator rejects invented numbers and requires exactly one action. Templates are the fallback.

## Results on 90 days of real data (`scripts/replay_sample.py`)

- 15,345 decisions and 251 notices across 7 replay users.
- **Volume:** default users get 1.6–2.3 event notices a week, plus optional morning check-ins. Delhi is the busiest, as it enters smog season.
- **Detection:** the Helsinki smoke on 24 August was caught at its first reading above normal. Every Mumbai sensor glitch (one-hour readings of 278–980 µg/m³, unflagged by OpenAQ) was ignored, with no notice.

## What building it changed

The replay surfaced design fixes, each covered by a test:
- a capped CUSUM, so one wild hour can't fire "elevated";
- a newest-hour jump is treated as suspect until the next hour confirms it, which stopped glitches leaking through severity escalation;
- re-checking the previous hour when a new one arrives;
- a ±6-hour catch window in the evaluation harness.

Each is now part of the design (explainer decisions 22–25) and the rule spec.

## Known limitations

- Three of the five stations are low-cost sensors (they read high in humid air). Bengaluru's only live sensor is labelled "indoor" by its owner.
- PM2.5 only.
- The harness's reference labels are sparse: one or two per station from change-point detection. So its false-alarm count is inflated and its catch rate is indicative only.
- Live ingestion works, as one tick or a scheduler, but the public demo runs on replayed real data, not a live feed.

## Process and tools

Built with Claude Code as orchestrator: parallel subagents per layer in isolated git worktrees, plus separate sessions for the watch demo, the Vercel deploy and the explainer video. Test-driven throughout: 225 core tests and 42 watch-demo tests. The live demo has 16 scenarios, each pinned to real replay decisions. Transcripts are in [transcripts/](transcripts/), and the notification history is in [notification-history/](notification-history/).
