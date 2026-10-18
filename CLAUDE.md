# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Greenfield. No code, build tooling, or tests exist yet — only the brief in `docs/` (the PDFs are gitignored and exist only in the local checkout; the summary below is the canonical copy). Once a stack is chosen and scaffolded, add the real build/run/test commands (including how to run a single test) to this file.

- `docs/explainer.md` — **the design source of truth**: the 18-layer model (S1–S3, U1–U3, D1–D8, A1–A2, L1–L2, plus RECORD/REPLAY/GUARD/OPERATE) at full and demo scope, with diagrams and the decision record. Design changes are made here first, closed with the user, then propagated to requirements, specs and QA.csv. Keep audit/review material out of it.
- `docs/requirements.md` — the spec: agreed product vision, v1 scope, decisions log and traceability to every brief requirement. Read it before designing or building; when a decision changes, update its section 8.
- `docs/QA.csv` — test cases, one row each, `requirement_ids` tracing to requirements.md and the brief. Every requirement ID has at least one row. Changing a requirement means updating its rows in the same change; implemented tests should reference their `test_id`.
- `docs/specs/S-A-openaq-and-schema.md` (OpenAQ API facts, chosen stations, storage schema), `S-B-rule-engine-research.md` (sources and rationale), `S-C-rule-engine-spec.md` (the detector, pipeline order, rule format, reason codes and all parameter defaults; the source of truth for decision logic).
- `data/samples/` — 90 days of hourly PM2.5 for the 5 tracked stations plus 2 fixtures (Mumbai glitches, Delhi reference gaps); used for replay and tests without an API key.
- `README.md` is for human readers only: plain prose about what, why and status. Keep agent instructions, internal conventions and spec detail out of it.
- `docs/Assignment_Orange.pdf` — the take-home brief. This is the source of truth for scope.
- `docs/Orange-Invest-JD-Founding-Engineer.pdf` — the role this assignment is for (Orange Invest, Founding Engineer). Useful for judging what the reviewers value: stateful async/event-driven backends, LLM infra (structured outputs, tool calling), queues (Temporal/BullMQ/Kafka/RabbitMQ), Redis, agent-step tracing and token/cost guardrails. Preferred stacks named there are TypeScript/Node.js or Python/FastAPI.

## What we're building: Proactive Air Quality Insight Agent

A backend service that watches air quality continuously and decides on its own when, and what, to proactively tell a user. The product goal is "only speak when something is worth knowing", so restraint (not notifying) is as important as detection.

Data source: OpenAQ (https://openaq.org/), 4–5 cities/stations, polled hourly.

### Core requirements (all mandatory)

1. **Ingestion** — hourly pull of new readings per station, stored with full history (trend detection needs it, not just the latest value).
2. **Insight/trigger logic** — detect patterns, not raw thresholds:
   - sustained trend (climbing for the last N hours)
   - sudden spike (sharp jump vs. recent baseline)
   - return to normal after a bad period
   - explicitly handle false positives and missed triggers
   - **primary detection must be a simple learned anomaly/change-point model on recent history** (e.g. rolling z-score / EWMA residuals, CUSUM, Bayesian online change-point) — fixed thresholds alone don't satisfy this.
3. **Dedup / rate limiting** — persistent per-user state of what has already been said; 6 straight bad hours must not produce 6 identical notifications. Re-notify only on a meaningful change.
4. **Message generation** — short natural-language notification text that references relevant past context and includes exactly one clear next action. Not JSON, not a template like "AQI is now 142", not a pure status update.
5. **Per-city / per-user sensitivity** — baselines differ by location: a user in a clean city gets a lower "unusual" bar than one in a naturally dusty region. Sensitivity should derive from each station's own learned baseline, optionally scaled per user.
6. **Observability** — an internal log/endpoint/dashboard showing what fired, when, why, and the exact data that triggered it, so a bad or missing nudge can be debugged later. Suppressed/deduped decisions should be recorded too, not just sent ones.

Out of scope: polished frontend, auth, multi-tenancy. A few hardcoded users per city is fine.

### Bonus

- Decay/cooldown so the system doesn't nag even after a legitimate re-trigger.
- Evaluation harness that replays historical OpenAQ data and reports interesting moments caught vs. missed. Designing ingestion/detection so it can run against a replayed clock (rather than wall-clock "now") makes this nearly free.

### Submission deliverables

GitHub repo, recorded demo video (e.g. Loom), decision/architecture note, transcript of coding tools/AI used, and conversation/notification history. Keep the architecture note and a notification history export in the repo as the work progresses.

## Domain notes

- OpenAQ reports pollutant concentrations (e.g. PM2.5 in µg/m³), not AQI. AQI must be computed from concentrations (e.g. US EPA breakpoints), and the choice should be documented.
- The current OpenAQ API (v3) requires a free API key sent as an `X-API-Key` header; older v1/v2 endpoints are retired. Keep the key in an env var, never in the repo.
- Station readings can be missing, delayed, or duplicated across polls; ingestion should be idempotent and the detector should tolerate gaps.
