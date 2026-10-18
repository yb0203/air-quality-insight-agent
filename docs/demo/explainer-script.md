# Explainer script: Proactive Air Quality Insight Agent

A five-minute spoken walkthrough for the Orange Invest founders, spoken by Yashvi in the first person. This is the **long version**, for a screen-recorded walkthrough (Loom). The **60-second vertical launch video** is cut from it: see [storyboard.md](storyboard.md) for its script and shot list, and [production-plan.md](production-plan.md) for how it gets made.

- **Audience:** founders hiring a Founding Engineer for a personal AI banker. They care about stateful async backends, LLM infra, observability and shipping fast.
- **What to land:** a systems thinker with a long horizon who also ships with tactical agility. The design is the full product; the demo is its first real slice.
- **Pace:** 744 spoken words at about 150 words a minute, so 4:58, with short pauses at scene changes. Spoken lines are the `>` quotes; everything else is direction.
- **Visuals:** each scene names what's on screen. **Pending build** marks a visual that needs the core service or the watch demo to exist before it can be captured. Everything else can be made now from the design doc and the 90-day sample.

| # | Time | Scene | Spoken words |
|---|---|---|---|
| 1 | 0:00–0:25 | Hook: restraint is the product | 62 |
| 2 | 0:25–0:58 | What it does: two notices | 93 |
| 3 | 0:58–2:00 | How it decides | 153 |
| 4 | 2:00–2:58 | Proof from real data | 143 |
| 5 | 2:58–3:40 | The demo moment: Delhi smog night | 96 |
| 6 | 3:40–4:08 | Every silence has a reason | 68 |
| 7 | 4:08–4:38 | The path to full scope | 77 |
| 8 | 4:38–5:00 | Close | 52 |
|  | **5:00** | **Total** | **744** |

---

## 1. Hook (0:00–0:25)

**On screen:** black. A phone lock screen fills with identical air quality alerts, one per hour, stacking until they blur. Cut to a single calm notice on a watch face. Title card: *Proactive Air Quality Insight Agent*.

> Nobody wants to check an air quality number every hour.
> What people want is something that watches for them, and taps them on the shoulder only when it matters.
> Spotting a high number is easy. Any script can do that.
> The hard part is restraint. Knowing when to stay quiet.
> So that's what I built. An agent where restraint is the product.

---

## 2. What it does (0:25–0:58)

**On screen:** two notices on a watch face, one after the other, each with its time stamp. The phrases with past context ("from about 1am", "after a rough 16 hours") and the one action are highlighted as they're read. Taken from the design's "night in Delhi" story; swap in real generated text once the build exists (**pending build** for the real text).

> Here's what it sounds like.
> Arjun lives in Delhi, and he runs every morning.
> At six thirty, he gets this. "Air got worse overnight from about 1am, and it's well above a normal Delhi morning. Maybe skip the outdoor run and try an indoor workout."
> And at five in the evening, this. "Delhi's air is back to its usual level after a rough sixteen hours. The evening looks fine for a run."
> Two messages in a day. Each one says what changed, how it compares to the past, and one thing to do.

---

## 3. How it decides (0:58–2:00)

**On screen:** four beats, each a diagram from the design doc redrawn as motion graphics.
1. *Normal per place:* the five-city "what normal looks like" bar chart (Helsinki 4.2 to Delhi 45.9 µg/m³).
2. *Unusual vs harmful:* the two-by-two grid. Only the top-right cell, "Tell them", lights up.
3. *One story:* the episode lifecycle (normal, active, recovering, closed), with three message dots: opened, got worse, cleared.
4. *Restraint in order:* the funnel, story half (worth it, pace) then person half (arbitrate, budget, timing). It pulls back to reveal the full eighteen-layer table.

> So how does it decide? Four ideas.
> First, it learns what's normal. For every station, and every hour of the day, it looks back two weeks. A reading of fifteen is alarming in Helsinki, and a calm afternoon in Delhi.
> Second, unusual isn't the same as harmful. The air also has to matter on the official US health scale. That's how a clean city gets a lower bar, without anyone hearing about harmless wobbles.
> Third, one bad period is one story. You hear when it starts, if it gets a full step worse, and when it's over. Not every hour in between.
> Fourth, restraint runs in order. First the story: is there anything new, and is it too soon? Then the person: which story wins this hour, how much attention have we used today, and is now a good moment?
> Under the hood, that's eighteen small layers. Each one answers a single question.

---

## 4. Proof from real data (2:00–2:58)

**On screen:**
1. A world map with five pins, coloured clean to dusty, each pin showing its median (from the city table).
2. The real Mumbai trace from the 90-day sample, 14 October: 65, 75, **980**, 90, 89 µg/m³. The 980 bar rises, gets a red "glitch" stamp, and greys out. A small caption: "8 such hours in 58 days. None flagged by the source."
3. The calibration table as a bar chart: notices per week per city, from 1.5 (Helsinki) to 3.5 (Delhi).
4. "53%" fills the screen. A flat-then-falling line labelled "trend?" gets crossed out and replaced by a rising one labelled "climb".

> I picked the cities from real data, not from a map. Helsinki, Los Angeles, Bengaluru, Dubai and Delhi. From very clean to naturally dusty.
> Ninety days of hourly readings ship with the code, so anyone can replay them without an API key.
> In Mumbai, one sensor jumps from seventy-five, to nine hundred and eighty, and back to ninety, in three hours. The data source doesn't flag it. So the agent checks every reading itself, and that glitch never becomes a message.
> Then I replayed all ninety days through an early version of the rules. A typical person got about one and a half messages a week in Helsinki, and three and a half in Delhi.
> And one number changed the design. Fifty-three percent of the hours I'd called a "trend" were actually flat, or falling. So now, a climb has to be rising.

---

## 5. The demo moment: Delhi smog night (2:58–3:40)

**On screen (pending build):** the watch demo, letterboxed, with its scenario chips. Tap "Delhi smog night". A clock scrubs from 22:00 to 06:30. At 01:00 a notice forms but slides into a "held" tray with a moon icon. At 02:00, 03:00 and 04:00 faint grey ticks appear, each tagged "same story". At 06:30 one notice lands with a gentle haptic. Then tap "Why?" and the reason card unfolds, layer by layer. A quick montage of the other chips closes the scene: "Helsinki smoke", "Glitch ignored", "Quiet night".

> Here it is on a watch. This is a smog night in Delhi.
> At one in the morning, the air starts climbing, and the agent opens a story. But it's quiet hours, so it holds the message instead of waking Arjun.
> Two, three, four am. Same story, same level. Nothing new to say.
> At six thirty, his morning check-in, he gets one message that covers the whole night.
> Tap "Why?", and the watch shows the reasoning, layer by layer.
> Other scenarios show smoke caught in Helsinki, a glitch ignored, and a quiet night with nothing sent.

---

## 6. Every silence has a reason (3:40–4:08)

**On screen (pending build):** the decision log for Arjun's night as a timeline: one row per hour, coloured by outcome (sent, held, suppressed, no event), each with its reason code. Zoom into the 02:00 row: its trace expands into plain sentences, then flips to the raw JSON from the explain endpoint. Overlay: a small "replay = live" badge.

> Behind the watch, every person gets a decision every hour, even when nothing is sent.
> Each one has an outcome, a reason, and the exact numbers behind it.
> So "why didn't I hear about it at two am?" has an answer, just as complete as "why did I?"
> And nothing reads the real clock. So replaying the past gives exactly the decisions the live system would have made.

---

## 7. The path to full scope (4:08–4:38)

**On screen:** the demo-scope layer table. Six stub rows glow amber, each with its one-line rule. They morph into their full-scope rows. A fusion card animates: air, heart rate and running merge into one message ("The air's turned unhealthy and your heart rate's up. Maybe walk the rest of the way home."). Then a guard gate drops in front of an "SOS" action.

> This demo is a first slice, not a throwaway. The eighteen layers are the same ones the full product needs.
> Six of them are stubs today. One named rule each, visible in every trace.
> When pollen or heart rate arrive, a fusion layer combines them. "The air's turned bad, and your heart rate's up."
> And before the agent ever calls for help, a guard layer checks consent and limits first.
> The seams are already in the code.

---

## 8. Close (4:38–5:00)

**On screen:** back to the single calm notice on the watch. Fade to three lines of text, one at a time: *Speaks rarely. Explains itself. Built to grow.* End card with the repo name.

> So, a design built for the long run, and a first slice that meets every requirement in the brief.
> An agent that speaks rarely, explains itself, and earns the right to interrupt.
> It's the same question a personal AI banker faces every day: when is something worth a message?
> Thanks for watching.

---

## Notes for recording

- **Numbers to keep honest.** The notices-per-week figures come from a replay of an *earlier* rule version; the line says "an early version of the rules". If the build's replay report gives new numbers, update scene 4 with them.
- **The two notices** are the illustrative ones from the design. If the generated wording differs, read the real text on screen and keep the spoken summary ("what changed, the past, one thing to do").
- **Words to say slowly:** "nine hundred and eighty", "fifty-three percent", "eighteen small layers".
- **Glossary for anyone re-recording:** *the official US health scale* is the EPA air quality category; *story* is an episode; *a full step worse* is a one-band escalation; *quiet hours* hold non-severe messages overnight; *check-in* is the person's chosen morning time.
