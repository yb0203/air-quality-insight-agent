# Production plan: phase 2, the 60-second vertical video

How the [storyboard](storyboard.md) becomes a rendered video, entirely on this machine. Phase 2 starts **when the watch demo front end is built** (its footage is the hero shot) and the core can produce decision traces and a replay report.

---

## 1. Ground rules

- **Rendered 100% locally.** No cloud rendering, no uploads, no hosted generation of music, voice or images.
- **Real material only** for the product: real watch demo footage, real decision rows and traces, real numbers from the 90-day sample and the replay report. Diagrams are redrawn from the design doc, never invented.
- **Only `docs/demo/**` changes.** The composition, scripts and assets live under `docs/demo/video/`.
- **Nothing gets installed without asking first.**

## 2. Tools

**HyperFrames** (HeyGen, open source, Apache 2.0) is the composition and render engine. A video is plain HTML: elements are clips with `data-start`, `data-duration` and `data-track-index`; animation is a paused GSAP timeline registered on `window.__timelines`; the root sets `data-width="1080" data-height="1920"` for vertical. Rendering seeks every frame in headless Chrome and encodes with FFmpeg, so the output is deterministic.

What's already on this machine: Node 26 (HyperFrames needs 22+), FFmpeg with the `ebur128`, `loudnorm`, `aevalsrc` and `anoisesrc` filters, Python 3.13 with NumPy, and the macOS `say` voice. SoX and Whisper aren't installed.

**To install, after asking.** The official routes, from the HyperFrames README:

```bash
claude plugin marketplace add heygen-com/hyperframes
```

```bash
claude plugin install hyperframes@hyperframes
```

Or a project-local install, which also brings in the skills:

```bash
npx hyperframes init docs/demo/video/composition
```

**Skills to read before building** (they ship with HyperFrames): `/hyperframes` (the router), `/product-launch-video` (brief, storyboard, review and production contracts), `/music-to-video` (beat-synced cutting), `/hyperframes-core` (tracks, sub-compositions, determinism), `/hyperframes-animation` and `/hyperframes-keyframes`, `/hyperframes-audio` (ducking, effect chains, submix buses), `/embedded-captions`, `/hyperframes-cli`. Useful catalog blocks: `npx hyperframes catalog`, for example `data-chart` and the shader transitions.

**Considered, not chosen:** Remotion (React, a strong alternative, but HyperFrames was requested); animation-studio and Tweenkit's kinetic-cut skill (good ideas for code-synthesised soundtracks and kinetic type, worth a look for reference only). No motion or video skills are installed today.

**Commands that are off-limits** because they leave the machine: `hyperframes cloud render`, `hyperframes lambda …`, `hyperframes publish`, and `/media-use` generation (it calls external text-to-speech, music and image models). Before the first render, check whether the CLI sends telemetry or usage calls (the skill mentions `npx hyperframes usage --json`), and switch it off or run without network if it does.

## 3. One score drives picture and sound

A single `beatmap.json` holds the tempo (120 BPM), the 30 bars, and every cue: shot cuts, text landings, sound effects, the filter sweep and the drop at 06:30. The composition reads it to place clips and tweens; the audio scripts read it to place sounds. Picture and sound can't drift apart, and moving a cue means editing one number.

## 4. Capturing the watch demo

The hero shot needs the watch front end to be **seekable**, so frames can be captured exactly and the edit can land on beats. What to ask of the front end (a hand-over note is in the shared notes folder for the watch demo session):

1. A capture mode by URL: scenario, simulated time, and a flag that pauses its own animations, for example `?scenario=delhi-smog-night&t=06:30&capture=1`.
2. Each key state reachable directly: the chip tapped, a held notice, "same story" ticks, the 06:30 notice, the "Why?" card open at each layer.
3. Rendering at 2× device pixel ratio with no browser chrome, and deterministic content (no live clock, no randomness).

With that, frames are captured as PNG sequences with a headless browser and placed as image clips, and the HyperFrames timeline animates between them. If a capture mode isn't possible, the fallback is a screen recording of the front end at 60 fps, trimmed to the beat map.

**From the core:** run a replay, export the replay report, and pull one night's decisions and the 02:00 trace from the explain endpoint as JSON. Shots 7 and 8 render from those files, so the numbers on screen are the real ones.

## 5. Sound

- **Music:** synthesised in code from the beat map (Python and NumPy, or FFmpeg's audio sources): a tension section with ticks, two beats of silence, a pluck build, a kick from bar 8, the low-passed "night" section, the drop at 06:30, a full groove for the proof, and a resolving chord. No licensing questions, and every hit lands on the grid. If it doesn't sound good enough, the fallback is a royalty-free track Yashvi supplies, with its licence recorded next to it.
- **Sound effects:** synthesised to match each movement: phone buzzes, a reverse riser into the cut, a sub hit, ticks and plucks, a soft whoosh down for the held notice, a haptic thump and watch buzz at 06:30, a stamp hit, a tick waterfall. Each one is timed to where its motion accelerates and lands, not pasted on every cut.
- **Voice-over (optional):** local text-to-speech (the Kokoro voice from Yashvi's setup, or macOS `say`), or Yashvi records it. Music ducks about 8–10 dB under the voice.
- **Mix:** about −14 LUFS integrated, true peak at or below −1 dBTP, measured with FFmpeg's `ebur128`.

## 6. Layout of `docs/demo/video/`

```
docs/demo/video/
  composition/     HyperFrames project: index.html, one sub-composition per shot, styles
  beatmap.json     tempo, bars and every cue
  assets/          captured watch frames, decision JSON, replay report, data extracts
  audio/           generation scripts, plus the rendered music, effects and voice stems
  out/             renders (ignored by git if over ~50 MB)
```

## 7. Render

- 1080 × 1920, 30 fps (60 if the watch footage is 60), H.264 High, yuv420p, AAC 48 kHz.
- Two cuts from the same composition: **voiced** and **music only**. Both have burned-in captions.
- A poster frame (the 06:30 notice) for thumbnails.
- At 60 seconds the renders should be well under 50 MB and can be committed. If not, they stay in `out/`, ignored, and the report says where they are.

## 8. Review checklist

- [ ] The first 3 seconds work muted, and the hook reads without sound.
- [ ] Every caption stays up long enough to read (about 3 words a second, never under 1 s) and sits inside the safe zone.
- [ ] Every cut and text landing is on a beat (±1 frame); the drop lands exactly at 06:30 on screen.
- [ ] Every number on screen matches the design doc, the sample or the replay report.
- [ ] The watch footage is the real front end, not a mock.
- [ ] No file paths, keys or personal data on screen.
- [ ] Loudness is about −14 LUFS with true peak at or below −1 dBTP.
- [ ] Watched on a phone, full screen, with sound on and with sound off.

## 9. Decisions left for phase 2

- Voiced or music-only as the main cut (recommendation: render both, then choose).
- Synthesised music, or a track Yashvi supplies.
- Whether the watch front end can offer the capture mode in §4, or a screen recording is used instead.

---

## 10. As built: first cut (2026-10-18)

The composition, scripts and README are in `docs/demo/video/`. Where the first cut differs from the storyboard, and why:

- **Shot 6 follows the real replayed night, not the design's example.** On the night of 8–9 August, Delhi was calm until 4:50am, then jumped sharply. The notice was held for quiet hours, 5:50 was "the same story", and one message went out at the 06:30 check-in. The watch ticks through real captures for every quiet hour, and the line under it shows each hour's real decision and reason code.
- **Shot 7 shows replay numbers, not the earlier calibration.** It shows event alerts a week per person, one person per city, read from the replay database: 1.6–2.3 at the time of the first cut.
- **Shot 8 zooms into the 06:30 message**, the real row behind the hero shot, and shows three lines of its real trace (episode, check-in, budget).
- **Voice-over is not in the first cut.** The music-only version comes first; a voiced version needs a local text-to-speech engine (Kokoro via `pip install kokoro-onnx soundfile`), which isn't installed yet.
- **The watch demo already had a capture mode** (`?scenario=…&t=…`), so no screen recording was needed.
- **Guardrails in practice:** HyperFrames telemetry is off, its skills were read from a scratch copy rather than installed into the Claude configuration, every font and script is bundled locally, and snapshots run with `--describe false` so no frame is sent for AI description.
