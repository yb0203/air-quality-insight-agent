# Air Quality Insight Agent

A service that watches the air in your city so you don't have to, and only speaks up when something is actually worth knowing.

> *"The air's been getting worse since 2am, and it's well above normal for a Delhi morning. Maybe skip the outdoor run today."*
>
> *"Back to normal in Helsinki after a smoky day and a half. Good time to open the windows."*

*(Illustrative examples of the kind of message it sends.)*

---

## The idea

Nobody wants to check an air quality number every hour. People want something that keeps an eye on it for them and taps them on the shoulder when it matters: when the air is turning bad, getting worse, or finally clearing up. They want the reason, and one thing to do about it.

The hard part isn't spotting a high number. The hard part is **restraint**. A useful agent knows what's normal for *your* city, doesn't repeat itself, doesn't wake you up for nothing, and can explain every decision it made, including the times it chose to stay quiet.

This is the first slice of a bigger idea: a proactive personal health agent. Today it watches air quality and sends notifications. The design leaves room for pollen and weather, wearable data like heart rate, other triggers like movement or smart-home sensors, and actions beyond a message.

## How it decides

1. **It learns what's normal for each place.** Every hour it pulls fresh readings from [OpenAQ](https://openaq.org) and learns each station's usual levels for each hour of the day over the last two weeks. A rise from 4 to 15 is a big deal in Helsinki. The same reading is a calm day in Delhi.
2. **It looks for patterns, not thresholds.** It watches for three things: a sudden spike, a sustained climb, and a slow build-up that never looks dramatic in any single hour. It also notices when things return to normal. It ignores sensor glitches.
3. **It checks whether the change matters to your health.** Being statistically unusual isn't enough. The air also has to reach a level that matters on the official air quality scale.
4. **It remembers what it already told you.** Each bad period is one story with a beginning, a middle and an end. You hear about it when it starts, if it gets meaningfully worse, and when it's over. Not every hour in between. It also keeps a daily limit on how much of your attention it uses.
5. **It respects your settings.** You can set quiet hours (only severe air gets through at night), an optional morning check-in, and how sensitive you are. Sensible defaults mean it works without any setup.
6. **It writes everything down.** Every decision is logged with the data and the reasoning behind it, including the decisions to stay quiet. "Why didn't I get warned?" always has an answer.

## Cities

| City | Why it's here |
|---|---|
| Helsinki | Very clean air. Small changes are unusual here. |
| Los Angeles | Clean to moderate, with occasional sharp jumps |
| Bengaluru | Moderate. Home of the team this was built for. |
| Dubai | Naturally dusty from the desert. A high baseline is normal. |
| Delhi | Heavily polluted, and heading into its seasonal smog right now |

## Where things stand

The design is complete and the build is next.

- [x] **How the agent decides**, with diagrams of every layer, at full scope and demo scope: [docs/explainer.md](docs/explainer.md). Start here.
- [x] Requirements, with every point in the original brief traced: [docs/requirements.md](docs/requirements.md)
- [x] Test cases for every requirement: [docs/QA.csv](docs/QA.csv)
- [x] Data source study and storage design: [docs/specs/S-A-openaq-and-schema.md](docs/specs/S-A-openaq-and-schema.md)
- [x] Research into how monitoring tools handle alerts: [docs/specs/S-B-rule-engine-research.md](docs/specs/S-B-rule-engine-research.md)
- [x] The decision rules, calibrated on 90 days of real data: [docs/specs/S-C-rule-engine-spec.md](docs/specs/S-C-rule-engine-spec.md)
- [ ] The service itself (Python)
- [ ] A replay harness that measures what it caught and missed on past data
- [ ] An architecture and decisions note, plus a demo

Setup and run instructions will appear here once the service exists.

## Built with

Python for the service. Possibly a small Next.js page on Vercel for the demo. The design and this repository were developed with Claude Code as a coding partner, and the session transcripts will be included with the submission.

## Data credits

Air quality data comes from [OpenAQ](https://openaq.org) and the original providers listed in [data/samples/stations.json](data/samples/stations.json): AirGradient sensor owners (CC BY 4.0), the US EPA AirNow program (US public domain) and the European Environment Agency (ODC-BY). A 90-day sample is included so the analysis can be reproduced without an API key.
