# Watch demo

A small, demo-only web app that shows the air quality agent's notifications the way a person would meet them: on a smartwatch. The watch sits in the middle of a black, letterboxed page. Everything inside the watch is the product: a stack of short notices, newest first, each with one suggested action, and a "Why you got this" view behind every notice. Everything outside the watch is the demo: chips to switch between scenarios, a one-line description of what you are looking at, and a note that the data is a replay of real OpenAQ readings.

![Delhi smog night](screenshots/01-delhi-smog-night.jpg)

## Why it exists

The agent's job is to speak rarely and well. A dashboard of decisions shows that it reasons; a watch face shows what that reasoning feels like on the receiving end: one calm message in the morning instead of six alarms overnight, an all-clear when the air recovers, and nothing at all when a sensor glitches.

It is deliberately separate from the agent itself. It never imports the agent's code. It either asks the running agent for its data over HTTP, or reads a set of example files shaped exactly like the agent's responses, so it runs offline with no API key.

## Running it

From the repository root:

```bash
uv run --project apps/watch_demo watch-demo
```

Then open http://localhost:8100. With no further setup it reads the example files in `fixtures/`. To point it at a running agent instead, set `AQAGENT_API_URL`, for example `AQAGENT_API_URL=http://localhost:8000`.

The tests run with:

```bash
uv run --project apps/watch_demo pytest apps/watch_demo/tests
```

## The scenarios

Each chip is one entry in `scenarios.yaml`: a person, a replay run, and the replayed moment the watch is showing.

- **Delhi smog night.** Arjun runs at 06:30. On the night of 8 to 9 October the air climbed from about 1am. The agent noticed, but it was quiet hours, so it held the notice and folded it into one message at his 06:30 check-in. When the episode ended at 17:00, after 16 hours, it sent a short all-clear.
- **Back to normal.** That all-clear on its own, with its reasons.
- **Helsinki smoke.** Aino has asthma and asked for high sensitivity. On 24 August smoke took Helsinki to about 27 µg/m³ against a usual 4. That is only "Moderate" on the official scale, but six times normal for this city, so she hears about it.
- **Glitch ignored.** A Mumbai sensor reported 980 µg/m³ for a single hour between readings of 75 and 90. The agent treated it as a glitch, and the watch stays calm.
- **Quiet night.** A normal Bengaluru night. Nothing worth saying, and the watch can still tell you why.

The readings behind these scenarios are real hours from the 90-day sample in `data/samples/`. The messages and decision records in `fixtures/` were written to match what the agent's rules produce for those hours; once the agent's API is running, the same screens can be driven from it directly.

## Screenshots

The `screenshots/` folder has each scenario and the "Why" views, taken from the running app.

## What it is not

It is not a product front end. There is no login, no settings, and no live updating; the page shows one replayed moment per scenario.
