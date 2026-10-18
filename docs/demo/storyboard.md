# Storyboard: the 60-second vertical launch video

The phase 2 deliverable: a **60-second, vertical (1080 × 1920)** launch video, cut on a musical beat grid, with kinetic type, motion graphics, sound design and real footage of the watch demo. It condenses the five-minute [explainer script](explainer-script.md). How it gets made, and with which tools, is in [production-plan.md](production-plan.md).

**Status:** planned. Production starts only when the watch demo front end is built, because its footage is the centrepiece (shot 6). Shots marked **pending build** need the watch front end or the core service; everything else can be made from the design doc and the 90-day sample.

---

## 1. The idea in one line

**The sound practises restraint too.** The video opens with a flood of identical alerts and noise, then cuts to real silence. During quiet hours the music goes muffled, as if heard through a wall. When the one message that matters lands at 06:30, the beat drops back in. Viewers *feel* the product's restraint before they read about it.

## 2. Format

| | |
|---|---|
| Canvas | 1080 × 1920, 9:16, 30 fps (60 fps only if the watch footage is captured at 60) |
| Length | 60.0 s exactly: 30 bars at 120 BPM |
| Beat grid | 1 beat = 0.5 s = 15 frames. 1 bar = 2 s = 60 frames. Cuts and text landings snap to beats (±1 frame) |
| Sound | Music bed, beat-locked sound effects, optional voice-over (see §6) |
| Captions | Burned in, always. Assume a muted first view: the story must work with sound off |
| Safe zone | Key text and UI inside x 90–990, y 240–1680 (keeps clear of platform overlays at the top, bottom and right edge; a rule of thumb, not a platform spec) |
| Type | One sans family (Inter or similar). Headlines 88–110 px, captions 56–64 px, data labels 36–44 px. Max ~6 words on screen per beat group |
| Colour | Near-black background (#0B0D10), off-white text. **One accent, orange, means "the agent speaks"**: only notices and "tell them" moments use it (a quiet nod to Orange Invest). The EPA band colours appear only inside data charts. Grey means "stayed quiet" |
| Motion | Entrances 8–12 frames, `expo.out` for slides and `back.out(1.6)` for pops. One focal point per beat. Text lands on downbeats. Hold every caption long enough to read: about 3 words a second, never under 1 s |

## 3. Beat map

Music structure at 120 BPM, which the cuts follow:

```
bar   1  2 | 3  4 | 5  6  7 | 8  9 10 | 11 12 13 | 14 15 16 17 | 18 19 20 | 21 22 23 | 24 25 26 | 27 28 | 29 30
time  0    4      8         14        20         26            34         40         46         52      56   60
music TENSION|SILENCE| BUILD (pluck arps, kick enters bar 8) |  NIGHT: low-pass, |  DROP     | FULL GROOVE (proof)  | RESOLVE
      ticks, |  then |                                       |  pad, heartbeat   |  06:30    |                      | chord +
      buzzes |  pad  |                                       |  kick             |  notice   |                      | ring-out
shot    1    |   2   |   3      |   4      |   5      |      6 (hero)          |   7      |   8      |  9   | 10
```

## 4. Shot list

Times are start–end. **VO** lines are the optional voice-over (§6); **TEXT** is burned in on screen whether or not there's a voice.

### Shot 1 · The flood · 0:00–0:04 · bars 1–2
- **Layout:** full-bleed phone lock screen, slightly tilted, filling the frame.
- **Motion:** identical notices ("AQI is now 142", "AQI is now 142", …) drop in on every eighth note, 16 in 4 seconds, stacking and compressing until the screen is a wall. Slight camera shake on each, increasing.
- **TEXT (top):** "Your air app." then, on beats: "Every." "Single." "Hour."
- **VO:** "Nobody wants an air alert every hour."
- **Sound:** a ticking hi-hat, a phone buzz per notice panned left and right, rising. A reverse riser crests at 0:03.9.
- **Assets:** drawn in HTML/CSS. Available now.

### Shot 2 · Silence · 0:04–0:08 · bars 3–4
- **Layout:** black, then a single watch face, centred, at about 60% of the width.
- **Motion:** hard cut on the downbeat of bar 3. Every notice vanishes. **Two beats of true silence** on black. On beat 3 the watch fades up and one calm notice slides in, edged with orange.
- **TEXT:** "What if it only spoke when it mattered?" (bar 3, beat 3), then the title lands on bar 4: **Proactive Air Quality Agent**.
- **VO:** "What if it only spoke when it mattered?"
- **Sound:** silence, then one soft chime and a warm pad entering.
- **Assets:** a watch frame and notice (from the watch demo's styling if ready; otherwise drawn). Available now as a mock; **pending build** for the real watch face.

### Shot 3 · Normal is local · 0:08–0:14 · bars 5–7
- **Layout:** five horizontal bars, one per city, stacked in the middle third.
- **Motion:** one bar grows per beat, Helsinki 4.2 → Los Angeles 10.0 → Bengaluru 20.7 → Dubai 41.0 → Delhi 45.9 µg/m³ (real 90-day medians). Then a vertical marker labelled **15** sweeps down the chart: Helsinki's row flashes "alarming", Delhi's row reads "a calm afternoon".
- **TEXT:** "It learns what's normal." / "Per city. Per hour."
- **VO:** "It learns what's normal for each city, at each hour."
- **Sound:** a rising pentatonic pluck per bar; a soft tick as the marker passes each row.
- **Assets:** real numbers from the 90-day sample. Available now.

### Shot 4 · Unusual × harmful · 0:14–0:20 · bars 8–10
- **Layout:** a 2 × 2 grid filling the width. Axes: "unusual here?" and "harmful?".
- **Motion:** the grid lines draw on beats. Three cells fill grey with "stay quiet". On the downbeat of bar 10 the top-right cell slams to orange: **TELL THEM**.
- **TEXT:** "Unusual isn't enough." / "It has to be harmful too."
- **VO:** "Unusual isn't enough. It has to be harmful too."
- **Sound:** the kick enters at bar 8. A sub hit on "TELL THEM".
- **Assets:** redrawn from the design's two-by-two diagram. Available now.

### Shot 5 · One story · 0:20–0:26 · bars 11–13
- **Layout:** a 24-hour timeline running top to bottom (vertical suits the canvas), hour ticks down the left.
- **Motion:** twelve red "bad hour" ticks rain in on eighth notes. Then they all fade to grey except three that pop orange on successive beats: **Opened**, **Got worse**, **Cleared**. A bracket draws round the whole night: "one story".
- **TEXT:** "One bad night = one story." / "Not twelve alerts."
- **VO:** "One bad night is one story. Not twelve alerts."
- **Sound:** muted clicks for the ticks, three bright plucks for the three messages.
- **Assets:** drawn. Available now.

### Shot 6 · Delhi smog night (hero) · 0:26–0:40 · bars 14–20 · pending build
- **Layout:** the watch demo, large and centred, with a clock readout above it and the caption band below. The scenario chip row is visible for the first beat.
- **Motion:**
  - 0:26: a tap ripple on the **Delhi smog night** chip.
  - 0:27–0:34: the clock scrubs 22:00 → 06:30. At **01:00** a notice starts to form, then slides down into a "held" tray with a moon icon. At **02:00, 03:00, 04:00** faint grey ticks appear, each tagged "same story".
  - **0:34, downbeat of bar 18: 06:30.** One notice lands, with a small screen shake. Its text fills the watch: "Air got worse overnight from about 1am, and it's well above a normal Delhi morning. Maybe skip the outdoor run today." The phrases "from about 1am" and "skip the outdoor run" get an orange underline.
  - 0:37–0:40: a tap on **Why?**. The reason card unfolds one layer per eighth note: episode opened → worth saying → held for quiet hours → check-in at 06:30 → sent.
- **TEXT:** "1am: worse. But it's quiet hours." → "2–4am: nothing new. Silence." → "6:30: one message for the whole night." → "Every decision explains itself."
- **VO:** "A smog night in Delhi. At 1am it gets worse, but it's quiet hours, so the message waits. At six thirty, one message covers the whole night. Tap why, to see its reasoning."
- **Sound:** **this is the restraint moment.** From bar 14 the music goes through a closing low-pass filter: muffled pad, a soft heartbeat kick, a muted click per held hour. At 06:30 the filter snaps open, the beat drops back in full, and the notice lands on a haptic thump plus a watch buzz. Fast soft ticks as the "Why?" layers unfold.
- **Assets:** real watch demo footage or frames (see production plan §4). Message text from the real core output if it's ready; otherwise the design's wording.

### Shot 7 · Proof, on real data · 0:40–0:46 · bars 21–23
- **Layout:** three full-screen stat cards, one per bar.
- **Motion:**
  1. Bar 21: the real Mumbai readings from 14 October, as a sparkline: 75 → **980** → 90 µg/m³. The spike gets a red stamp, **GLITCH · IGNORED**, and greys out. Small line: "the source didn't flag it."
  2. Bar 22: **1.5–3.5 notices a week**, five bars, one per city, clean to dusty.
  3. Bar 23: **53%** of first-draft "trends" were flat or falling. A flat line is crossed out; a rising one replaces it, labelled "climb must rise".
- **TEXT:** as on the cards, plus a header: "90 days. 5 cities. Real data."
- **VO:** "Tested on ninety days of real data. It ignores glitches, and speaks two or three times a week."
- **Sound:** a stamp hit per card, groove at full energy.
- **Assets:** the Mumbai trace and medians from the sample (available now). Notices per week: the design's calibration, or the replay report's numbers once the core runs (**pending build** for the refreshed numbers).

### Shot 8 · Every silence has a reason · 0:46–0:52 · bars 24–26 · pending build
- **Layout:** the decision log as a waterfall of rows, one per hour, filling the frame.
- **Motion:** rows cascade in on sixteenth notes, coloured by outcome: orange sent, blue held, grey suppressed. Reason codes are legible on the near rows: `QUIET_HOURS_HELD`, `DEDUP_SAME_BAND`, `COOLDOWN`, `SENT_CHECK_IN`. On bar 26 the camera pushes into the 02:00 row, which opens into its trace as plain sentences.
- **TEXT:** "Every hour, logged." / "Every silence, explained."
- **VO:** "Every decision is logged. Even the silences have a reason."
- **Sound:** a fast tick waterfall, then a soft whoosh into the push-in.
- **Assets:** real decision rows and a real trace from the core's decision log and explain endpoint.

### Shot 9 · Built to grow · 0:52–0:56 · bars 27–28
- **Layout:** the eighteen layers as a 5-plane grid of tiles.
- **Motion:** tiles assemble in a fast stagger. Six stub tiles glow amber. Then three icons pop in at the full-scope layers: pollen, a heart rate line, an SOS shield behind a guard gate.
- **TEXT:** "18 layers." / "Air today. Pollen, heart rate, SOS next."
- **VO:** "Eighteen layers. Air today. Pollen, heart rate and SOS next."
- **Sound:** a rising arpeggio; three pops for the icons.
- **Assets:** drawn from the design's layer tables. Available now.

### Shot 10 · End card · 0:56–1:00 · bars 29–30
- **Layout:** the single calm watch notice from shot 2, then the end card.
- **Motion:** the watch shrinks to an icon; two lines land on downbeats: **Speaks rarely.** **Explains itself.** Then the project name and repo address in small type.
- **VO:** "Speaks rarely. Explains itself."
- **Sound:** the music resolves on the downbeat of bar 30 and rings out to silence at 1:00.
- **Assets:** drawn. Available now.

## 5. Asset list

| Asset | Source | Ready? |
|---|---|---|
| City medians, Mumbai glitch trace | 90-day sample in the repo | now |
| Diagrams (2 × 2 grid, story timeline, layer grid) | redrawn from the design doc | now |
| Watch face, chips, held tray, "Why?" card | watch demo front end | pending build |
| Real notice text for Delhi smog night | core output, or the design's wording | pending build |
| Decision rows and a trace | core decision log and explain endpoint | pending build |
| Notices per week, caught vs missed | replay report from the core | pending build |
| Music, sound effects | generated locally in code from the beat map | phase 2 |
| Voice-over | local text-to-speech or Yashvi's recording | phase 2 |

## 6. Voice-over: optional, decided in phase 2

The video is designed to work **muted**, with captions carrying the story. A voice-over track sits on top as an option: 118 words across 60 seconds, about 2 words a second, which leaves room for the music and the silence in shot 2. Recommendation: render both, a voiced cut and a music-only cut, from the same composition, and choose after watching them.

Full voice-over, in order:

> Nobody wants an air alert every hour.
> What if it only spoke when it mattered?
> It learns what's normal for each city, at each hour.
> Unusual isn't enough. It has to be harmful too.
> One bad night is one story. Not twelve alerts.
> A smog night in Delhi. At 1am it gets worse, but it's quiet hours, so the message waits. At six thirty, one message covers the whole night. Tap why, to see its reasoning.
> Tested on ninety days of real data. It ignores glitches, and speaks two or three times a week.
> Every decision is logged. Even the silences have a reason.
> Eighteen layers. Air today. Pollen, heart rate and SOS next.
> Speaks rarely. Explains itself.
