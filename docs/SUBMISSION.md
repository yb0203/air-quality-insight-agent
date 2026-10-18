# Submission checklist

What the brief asked for, and where each piece is.

## Deliverables

| Brief asks for | Where | Status |
|---|---|---|
| GitHub repository | [yb0203/air-quality-insight-agent](https://github.com/yb0203/air-quality-insight-agent) | ✅ |
| Recorded demo video | 60-second launch video: [demo/video/air-agent-60s-vertical.mp4](https://github.com/yb0203/air-quality-insight-agent/blob/main/docs/demo/video/air-agent-60s-vertical.mp4) (rendered locally with HyperFrames). 5-minute walkthrough script: [demo/explainer-script.md](demo/explainer-script.md). Live demo: <https://air-quality-watch-demo.vercel.app> | ✅ |
| Decision / architecture note | [architecture-note.md](architecture-note.md) (short); [explainer.md](explainer.md) (full design with diagrams) | ✅ |
| Transcript of coding tools / AI used | [transcripts/](transcripts/): Claude Code session transcripts (JSONL) for the orchestrator, its subagents, and the watch-demo, Vercel-deploy and explainer-video sessions | ✅ |
| Conversation / notification history | [notification-history/](notification-history/): every notice each demo user received over the 90-day replay | ✅ |

## Core requirements

| # | Requirement | How it's met | Proof |
|---|---|---|---|
| 1 | Ingestion: hourly, with history | Trailing 24h window, revisions kept, backfill, as-known reads | `tests/test_ingest.py`, `tests/test_repo.py` |
| 2 | Trend, spike, return to normal, false positives, missed triggers, learned model | Per-station hour-of-day baseline (median/MAD); spike, climb, elevated and clearing; glitch checks; clock tick for silent sensors | `tests/test_trigger.py`, `test_episode.py`, `test_validate.py`, `test_replay.py` (Helsinki smoke caught, Mumbai glitches ignored) |
| 3 | Dedup / rate limiting | Episodes with flap guard; worth-it, pace (6→12→24h), arbitration, daily budget | `tests/test_pipeline.py` (six bad hours → one notice) |
| 4 | Natural messages with past context and one action | Structured facts → LLM or template, validated (no invented numbers, exactly one action) | `tests/test_compose.py`, [notification-history/](notification-history/) |
| 5 | Different baselines per city and user | Station-relative "unusual" plus absolute EPA "harmful"; per-user sensitivity | `test_qa_det_10`, `test_qa_sens_*` |
| 6 | Observability | Decision row per user per hour, with reason code and layer trace; explain API | `tests/test_api.py`, the watch "Why?" view |
| Bonus | Decay / cooldown | Pace doubles within an episode; severe bypass | `test_qa_dedup_05` |
| Bonus | Evaluation harness | Replays 90 days as-known; caught / missed / false alarms / volume | `scripts/replay_sample.py`, `tests/test_replay.py` |

Every requirement has test cases in [QA.csv](QA.csv) (102 rows). The suite has 225 core tests and 42 watch-demo tests. The live demo has 16 scenarios, each pinned to real decisions from the replay, plus a capabilities page (/capabilities) mapping each brief requirement to the scenarios that show it.

## Try it

- **Demo:** <https://air-quality-watch-demo.vercel.app>. Pick a scenario chip, then tap a notice to see why it was sent.
- **Locally:** see the README's "Try it" section.
