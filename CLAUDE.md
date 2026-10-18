# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A proactive air quality insight agent: a take-home for Orange Invest (Founding Engineer). It polls OpenAQ PM2.5 hourly for five cities, learns each station's normal level per hour of day, detects spike, climb and elevated events, tracks episodes, applies restraint, and writes short messages with past context and one action. Every decision is logged with a reason code and a layer-by-layer trace. The public demo is a separate watch app at https://air-quality-watch-demo.vercel.app.

## Commands

```bash
uv sync --all-extras                                   # all deps incl. eval extras (numpy, ruptures) needed by tests
uv run pytest -q                                       # full core suite (~4 min; includes a full 90-day replay)
uv run pytest -q --ignore=tests/test_replay.py         # fast core suite (~25 s)
uv run pytest tests/test_pipeline.py::test_qa_dedup_01_six_bad_hours_one_notice -q   # one test
uv run python scripts/replay_sample.py                 # replay data/samples into data/replay.db and print the report
uv run python scripts/export_watch_fixtures.py         # regenerate apps/watch_demo fixtures + scenarios from data/replay.db
uv run python scripts/serve_api.py                     # core API on :8000 over data/replay.db
uv run python scripts/tick_once.py                     # one live hour against OpenAQ (needs OPENAQ_API_KEY in .env)
uv run python scripts/run_live.py                      # live scheduler: hourly at :20 UTC + check-ins + quiet-hours ends
uv run --project apps/watch_demo pytest apps/watch_demo/tests -q   # watch demo tests
uv run --project apps/watch_demo watch-demo            # watch demo on :8100 (fixtures)
```

There is no CLI. Operations are plain functions in `aqagent.ops`, called from `scripts/`. A plain `uv sync` drops the eval extras and breaks `tests/test_replay_load.py`, so always use `--all-extras`.

## Architecture

The design source of truth is `docs/explainer.md`: 18 layers, shown at full scope and demo scope. Exact logic and every parameter are in `docs/specs/S-C-rule-engine-spec.md`, and all values live in `src/aqagent/params.py`. Change the design in the explainer first, close it with the user, then carry the change into requirements, specs and `docs/QA.csv`.

How the layers map to code (`src/aqagent/`):
- **Sense:** `sense/openaq.py` and `sense/ingest.py` (S1, trailing 24 h window, revisions kept, backfill), `sense/validate.py` (S2 data quality; a newest-hour jump is suspect until the next hour), `sense/resolve.py` (S3 stub).
- **Understand:** `understand/baseline.py` (U1 hour-of-day median/MAD), `understand/score.py` (U2 z, EWMA, clipped CUSUM, slope, NowCast and band; shared per station, never per user), `understand/aqi.py` (EPA 2024 bands).
- **Decide:** `decide/trigger.py` (D1 spike, climb, elevated, floor, calm; user sensitivity scales the bars), `decide/episode.py` (D2 lifecycle, flap guard, 24 h no-data close), `decide/restraint.py` (D3 worth it, D4 pace, D5 arbitrate stub, D6 respond stub, D7 budget, D8 timing) and `decide/pipeline.py` (the per-user order, as pure functions), with `decide/rules.py` holding the user rule model.
- **Act:** `act/facts.py` and `act/compose.py` (A1: an insight from verified facts, then LLM or template, then a validator), `act/deliver.py` (A2 stub: write to the feed).
- **Wiring:** `runner.py`, with two triggers: `data_run` for new or revised hours and `clock_tick` for silence, check-ins and quiet-hours release. It also re-checks the previous hour on each arrival.
- **Storage and API:** `db.py` and `repo.py` (SQLAlchemy Core; SQLite, Postgres-ready; readings are append-only revisions for as-known reads), `queries.py` and `api.py` (read API), `learn/feedback.py`.
- **Replay:** `replay/load.py` (the sample with synthetic arrival times), `replay/harness.py` (a simulated clock over hourly ticks, check-ins and quiet ends, plus the report), `replay/labels.py` (ruptures reference labels; must not import `aqagent.decide`).

Invariants:
- Nothing under `src/aqagent/` except `clock.py` reads wall-clock time. A test enforces this.
- Every hour is recomputed from the readings known at that moment, so replay equals live.
- Replays use their own database (`data/replay.db`).

## Docs and data

- `docs/requirements.md`: the spec, traced to the brief. `docs/QA.csv`: one row per test case, keyed by `requirement_ids`. Tests are named `test_qa_<id>_…` so they trace back to a row.
- `docs/architecture-note.md` (short) and `docs/SUBMISSION.md` (the deliverables checklist).
- `data/samples/`: 90 days of hourly PM2.5 for 5 tracked stations plus 2 fixtures (Mumbai glitches, Delhi reference gaps). Licences are in `stations.json`.
- `config/users.yaml` (the 6 demo users) and `config/fixture_users.yaml` (Rohan on Mumbai, for replay only).
- `apps/watch_demo/` is the decoupled demo app, its own uv project. It reads fixtures exported from the replay, and deploys to Vercel from `main` through `index.py` and `vercel.json`. Its hand-written test fixtures are in `apps/watch_demo/tests/data/`.
- `README.md` is for human readers only. Keep agent instructions out of it.

## OpenAQ facts that bite

- v3 needs an `X-API-Key` header on every call. The limits are 60 requests a minute and 2,000 an hour.
- OpenAQ reports concentrations, not AQI.
- Indian periods end at `:30 UTC`.
- Missing hours are simply absent.
- Glitches are not flagged, so S2 has to catch them.
- On this Mac, Python's urllib needs `SSL_CERT_FILE=/etc/ssl/cert.pem`. httpx uses certifi and is fine.
