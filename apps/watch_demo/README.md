# Watch demo

A small, demo-only web app that shows the air quality agent's notifications the way a person would meet them: on a smartwatch, with the data behind them laid out beside it.

The page has two halves. On the right is the watch. Everything inside it is the product: a stack of short notices, newest first, each with one suggested action, and a "Why you got this" view behind every notice. On the left is a chart of what the agent actually saw: the station's hourly PM2.5, the usual level for each hour of the day, the official air quality bands behind them, and a lane underneath with one mark for every hour the agent decided something: a filled dot where it sent a message, a ring where it held one for later, a small tick where it had nothing new to say.

Click any hour on the chart and the watch jumps to that moment. In the Delhi scenario, 1am shows the watch in quiet hours with something held; 6:30am shows the single check-in message arriving; 5pm shows the all-clear. Below the chart, a short line names the decision for that hour and the reason the agent recorded. Everything outside the watch (the chart, the scenario chips, the description and a note that the data is a replay of real OpenAQ readings) is the demo frame.

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

Each chip is one entry in `scenarios.yaml`: a person, a replay run, the replayed moment the watch opens at, and how many hours of history the chart shows.

- **Delhi smog night.** Arjun runs at 06:30. On the night of 8 to 9 October the air climbed from about 1am. The agent noticed, but it was quiet hours, so it held the notice and folded it into one message at his 06:30 check-in. When the episode ended at 17:00, after 16 hours, it sent a short all-clear.
- **Back to normal.** That all-clear on its own, with its reasons.
- **Helsinki smoke.** Aino has asthma and asked for high sensitivity. On 24 August smoke took Helsinki to about 27 µg/m³ against a usual 4. That is only "Moderate" on the official scale, but six times normal for this city, so she hears about it.
- **Glitch ignored.** A Mumbai sensor reported 980 µg/m³ for a single hour between readings of 75 and 90. The agent treated it as a glitch, and the watch stays calm.
- **Quiet night.** A calm Bengaluru night, cleaner than usual. Nothing worth saying, and the watch can still tell you why.

The readings behind these scenarios are real hours from the 90-day sample in `data/samples/`. The messages and decision records in `fixtures/` were written to match what the agent's rules produce for those hours; once the agent's API is running, the same screens can be driven from it directly.

## Screenshots

The `screenshots/` folder has each scenario and its "Why" view, plus two moments from the Delhi night (1am, held; 6:30am, the check-in), taken from the running app.

## What it is not

It is not a product front end. There is no login, no settings, and no live updating; it replays recorded moments. It also uses no JavaScript: the chart is drawn on the server, and every hour on it is an ordinary link.
