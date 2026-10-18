# The 60-second launch video

A vertical (1080 × 1920) launch video for the air quality agent, made from the [storyboard](../storyboard.md) with [HyperFrames](https://github.com/heygen-com/hyperframes), an HTML-to-video renderer. Everything is rendered locally: no cloud rendering, no uploads, no hosted generation.

Everything on screen is real: the watch screens are captured from the watch demo, the decision rows and the trace come from the replay behind it, and the numbers come from the 90-day sample and the replay database.

## How it fits together

- `beatmap.json` is the one score: 120 BPM, 30 bars, every cut, caption and sound cue. Picture and sound both read it, so they can't drift apart.
- `scripts/build_assets.py` reads the built agent (the sample, `data/replay.db` read-only, and the watch demo fixtures) and writes `composition/assets/data.js` and `beatmap.js`.
- `scripts/capture_watch.mjs` photographs the running watch demo at each replayed moment of the Delhi night, at 3× resolution.
- `scripts/make_audio.py` synthesises the music and sound effects in code from the beat map, then levels the mix to about −14 LUFS with true peak at −1 dBTP.
- `composition/` is the HyperFrames project: `index.html` (ten shots), `assets/styles.css`, and `assets/main.js`, which builds the timeline from the beat map and the data.

## Rebuild

From the repository root, with a checkout that has the built agent (by default, the main checkout):

```bash
npm --prefix docs/demo/video install
```

```bash
uv run --project apps/watch_demo python docs/demo/video/scripts/build_assets.py
```

Start the watch demo (`WATCH_DEMO_PORT=8100 uv run --project apps/watch_demo watch-demo`), then:

```bash
node docs/demo/video/scripts/capture_watch.mjs http://127.0.0.1:8100
```

```bash
python3 docs/demo/video/scripts/make_audio.py
```

```bash
cd docs/demo/video/composition && HYPERFRAMES_NO_TELEMETRY=1 npx hyperframes render . -o ../out/air-agent-60s.mp4 --fps 30
```

Use `npx hyperframes check .` before rendering, and pass `--describe false` to `snapshot` so no frame is sent for AI description. HyperFrames telemetry is switched off on this machine. Never use the `cloud`, `lambda`, `cloudrun` or `publish` commands for this project.

## Credits

Fonts: Inter and JetBrains Mono (SIL Open Font License, licences in `composition/assets/fonts/`). Animation: GSAP. Music and sound: synthesised for this video. Data: OpenAQ and its providers, as credited in the main README.
