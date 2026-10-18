/* Proactive Air Quality Agent: the 60 s timeline.
   Every time comes from window.BEATMAP (beatmap.json); every number and line of product text
   from window.DATA (extracted from the real sample, replay and watch demo by build_assets.py). */
window.buildMainTimeline = function () {
  const B = window.BEATMAP, C = B.cues, D = window.DATA;
  const tl = gsap.timeline({ paused: true });
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  // Seeded PRNG: same layout every render.
  let seed = 20261018;
  const rand = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const IN = "expo.out", POP = "back.out(1.7)";

  // Show a text element: rise and fade in. Optionally hide it again.
  function show(target, t, opts = {}) {
    tl.fromTo(target, { opacity: 0, y: opts.dy ?? 36 }, { opacity: 1, y: 0, duration: opts.d ?? 0.4, ease: IN }, t);
    if (opts.out != null) tl.to(target, { opacity: 0, y: -16, duration: 0.15, ease: "power2.in" }, opts.out - 0.15);
  }
  const ampm = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); const h12 = h % 12 || 12; return `${h12}${m ? ":" + String(m).padStart(2, "0") : ""}${h < 12 ? "am" : "pm"}`; };
  const BAND = { good: "Good", moderate: "Moderate", usg: "Unhealthy for sensitive groups", unhealthy: "Unhealthy", very_unhealthy: "Very unhealthy", hazardous: "Hazardous" };
  const bandOf = (v) => (v <= 9.0 ? "good" : v <= 35.4 ? "moderate" : v <= 55.4 ? "usg" : v <= 125.4 ? "unhealthy" : v <= 225.4 ? "very_unhealthy" : "hazardous");
  const bandColor = { good: "var(--good)", moderate: "var(--moderate)", usg: "var(--usg)", unhealthy: "var(--unhealthy)" };

  /* ---------- 1 · the flood ---------- */
  const cards = $("#s01-cards");
  C.flood_notices.forEach((t, i) => {
    const c = el("div", "ncard", `<div class="icon">AQ</div><div class="txt"><div class="app"><span>AIR ALERT</span><span>now</span></div><div class="msg">AQI is now 142</div></div>`);
    c.style.top = `${250 + rand() * 1080}px`;
    cards.appendChild(c);
    const rot = (rand() - 0.5) * 7, dx = (rand() - 0.5) * 70;
    tl.fromTo(c, { opacity: 0, y: -60, x: dx, rotation: rot, scale: 1.08 }, { opacity: 1, y: 0, scale: 1, duration: 0.16, ease: "power3.out" }, t);
    const s = 4 + 18 * (i / C.flood_notices.length);
    tl.fromTo("#s01-cam", { x: (i % 2 ? s : -s), y: -s * 0.6 }, { x: 0, y: 0, duration: 0.14, ease: "power2.out", immediateRender: false }, t);
  });
  tl.fromTo("#s01-cards", { scale: 1 }, { scale: 1.07, duration: 0.5, ease: "power2.in" }, 3.5);
  ["#s01-w0", "#s01-w1", "#s01-w2", "#s01-w3"].forEach((w, i) => {
    const t = C.flood_words[i], next = C.flood_words[i + 1];
    tl.fromTo(w, { opacity: 0, scale: i ? 1.25 : 1, y: i ? 0 : 30 }, { opacity: 1, scale: 1, y: 0, duration: i ? 0.12 : 0.3, ease: "power3.out" }, t);
    if (next != null) tl.to(w, { opacity: 0, duration: 0.06 }, next - 0.06);
  });

  /* ---------- 2 · silence ---------- */
  show("#s02-q", C.question, { d: 0.6 });
  tl.fromTo("#s02-watch", { opacity: 0, scale: 0.9, y: 30 }, { opacity: 1, scale: 1, y: 0, duration: 0.9, ease: IN }, C.watch_in);
  tl.fromTo("#s02-title .kicker", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.4, ease: IN }, C.title);
  tl.fromTo("#s02-title .title", { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.6, ease: IN }, C.title + 0.08);

  /* ---------- 3 · normal is local ---------- */
  show("#s03-h1", 8.0);
  show("#s03-h2", C.normal_line2);
  show("#s03-note", 8.25, { dy: 10 });
  const MAXV = 50;
  const chart = $("#s03-chart");
  D.cities.forEach((c, i) => {
    const band = bandOf(c.median);
    const row = el("div", "city", `<span class="name">${c.city}</span><span class="band" style="color:${bandColor[band]}">${BAND[band]}</span>
      <div class="track"><div class="bar"></div></div><div class="val">${c.median}</div><div class="pill"></div>`);
    row.id = `s03-row${i}`;
    chart.appendChild(row);
    const t = C.city_bars[i];
    tl.fromTo(row, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.3, ease: IN }, t - 0.05);
    tl.fromTo(row.querySelector(".bar"), { scaleX: 0, width: "100%" }, { scaleX: c.median / MAXV, duration: 0.5, ease: IN }, t);
    tl.fromTo(row.querySelector(".val"), { opacity: 0 }, { opacity: 1, duration: 0.2 }, t + 0.2);
  });
  // The 15 µg/m³ marker sweeps down the chart: alarming in Helsinki, a calm afternoon in Delhi.
  const trackW = 900 - 150;
  const marker = el("div", "marker"); marker.style.left = `${(15 / MAXV) * trackW}px`;
  const mlabel = el("div", "marker-label", "15 µg/m³"); mlabel.style.left = `${(15 / MAXV) * trackW}px`;
  chart.appendChild(marker); chart.appendChild(mlabel);
  tl.fromTo(marker, { scaleY: 0 }, { scaleY: 1, duration: C.marker_sweep[1] - C.marker_sweep[0], ease: "none" }, C.marker_sweep[0]);
  tl.fromTo(mlabel, { opacity: 0 }, { opacity: 1, duration: 0.2 }, C.marker_sweep[0]);
  const first = $("#s03-row0 .pill"), last = $(`#s03-row${D.cities.length - 1} .pill`);
  first.classList.add("alarm"); first.textContent = `15 here: ${(15 / D.cities[0].median).toFixed(1)}× normal`;
  last.classList.add("calm", "below"); last.textContent = "15 here: a calm day";
  tl.fromTo(first, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.35, ease: POP }, C.helsinki_alarm);
  tl.fromTo(last, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.35, ease: POP }, C.delhi_calm);

  /* ---------- 4 · unusual × harmful ---------- */
  show("#s04-h1", C.grid_draw);
  show("#s04-h2", C.grid_line2);
  tl.fromTo("#s04-gv", { scaleY: 0 }, { scaleY: 1, duration: 0.5, ease: IN }, C.grid_draw);
  tl.fromTo("#s04-gh", { scaleX: 0 }, { scaleX: 1, duration: 0.5, ease: IN }, C.grid_draw + 0.1);
  tl.fromTo(".axis-top, .axis-left", { opacity: 0 }, { opacity: 1, duration: 0.4 }, C.grid_draw + 0.2);
  ["#s04-c0", "#s04-c2", "#s04-c3"].forEach((c, i) => {
    tl.fromTo(c, { opacity: 0, scale: 0.92, backgroundColor: "rgba(28,28,30,0)" }, { opacity: 1, scale: 1, backgroundColor: "rgba(28,28,30,1)", duration: 0.35, ease: IN }, C.grid_quiet_cells[i]);
  });
  tl.fromTo("#s04-c1", { opacity: 0, scale: 1.3, backgroundColor: "rgba(255,122,26,1)", color: "#111111" }, { opacity: 1, scale: 1, duration: 0.3, ease: POP }, C.tell_them);

  /* ---------- 5 · one story ---------- */
  show("#s05-h1", C.story_ticks[0]);
  show("#s05-h2", C.story_grey);
  const list = $("#s05-list");
  const hours = ["10pm", "11pm", "12am", "1am", "2am", "3am", "4am", "5am", "6am", "7am", "8am", "9am"];
  const labels = { 0: "Opened", 5: "Got worse", 11: "Cleared" };
  const rows5 = hours.map((h, i) => {
    const r = el("div", "srow", `<div class="bgfill"></div><span class="t">${h}</span><span class="m">${i === 11 ? "Back to usual" : "Air is unhealthy"}</span><span class="lbl">${labels[i] ?? ""}</span>`);
    list.appendChild(r);
    tl.fromTo(r, { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.18, ease: "power3.out" }, C.story_ticks[i]);
    return r;
  });
  tl.to(rows5.map((r) => r.querySelector(".bgfill")), { backgroundColor: "#16181c", duration: 0.3 }, C.story_grey);
  tl.to(rows5.map((r) => r.querySelector(".m")), { color: "#48484a", duration: 0.3 }, C.story_grey);
  tl.to(rows5.map((r) => r.querySelector(".t")), { color: "#48484a", duration: 0.3 }, C.story_grey);
  [0, 5, 11].forEach((i, k) => {
    const t = C.story_messages[k], r = rows5[i];
    tl.to(r.querySelector(".bgfill"), { backgroundColor: "#ff7a1a", duration: 0.12 }, t);
    tl.to([r.querySelector(".m"), r.querySelector(".t")], { color: "#111111", duration: 0.12 }, t);
    tl.fromTo(r, { scale: 1.06 }, { scale: 1, duration: 0.35, ease: POP, immediateRender: false }, t);
    tl.fromTo(r.querySelector(".lbl"), { opacity: 0, x: 20 }, { opacity: 1, x: 0, duration: 0.25, ease: IN }, t + 0.05);
  });
  tl.fromTo("#s05-bracket", { scaleY: 0, opacity: 0 }, { scaleY: 1, opacity: 1, duration: 0.5, ease: IN }, C.story_bracket);

  /* ---------- 6 · a real night in Delhi ---------- */
  const W = D.watch, night = W.night;
  tl.fromTo(".s06-head .eyebrow", { opacity: 0 }, { opacity: 1, duration: 0.3 }, C.chip_tap - 0.0);
  tl.fromTo("#s06-chips", { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.2 }, C.chip_tap);
  const ripple = (sel, t, d) => {
    tl.fromTo(sel, { opacity: 0, scale: 0.4 }, { opacity: 1, duration: 0.01 }, t);
    tl.to(sel, { opacity: 0, scale: 1.5, duration: d, ease: "power2.out" }, t + 0.01);
  };
  ripple("#s06-tap1", C.chip_tap + 0.05, 0.5);
  tl.to("#s06-chips", { opacity: 0.35, duration: 0.4 }, C.chip_tap + 1.0);
  tl.fromTo("#s06-watch", { opacity: 0, scale: 0.94 }, { opacity: 1, scale: 1, duration: 0.5, ease: IN }, C.chip_tap + 0.1);
  // Watch screens: the real app at each moment.
  ["#s06-w-held", "#s06-w-checkin", "#s06-w-why"].forEach((s) => tl.set(s, { opacity: 0 }, 0));
  tl.to("#s06-w-held", { opacity: 1, duration: 0.25 }, C.held);
  tl.to("#s06-w-evening", { opacity: 0, duration: 0.25 }, C.held);
  {
    const ns = night, i0 = Math.max(0, ns.findIndex((r) => r.t === "22:50")), ih = ns.findIndex((r) => r.code === "QUIET_HOURS_HELD");
    const hrs = ns.slice(i0, ih), n0 = C.night_ticks[0], n1 = C.night_ticks[C.night_ticks.length - 1];
    const before = $("#s06-w-held");
    hrs.forEach((r, i) => {
      if (i === 0) return; // the evening frame is the first hour
      const img = el("img"); img.src = `assets/watch/night-${r.t.replace(":", "")}.png`; img.alt = "";
      before.parentNode.insertBefore(img, before);
      const t = n0 + (i * (n1 - n0)) / Math.max(hrs.length - 1, 1);
      tl.fromTo(img, { opacity: 0 }, { opacity: 1, duration: 0.06 }, t);
      tl.to(img, { opacity: 0, duration: 0.25 }, C.held);
    });
  }
  tl.set("#s06-w-checkin", { opacity: 1 }, C.drop);
  tl.set("#s06-w-held", { opacity: 0 }, C.drop + 0.04);
  tl.fromTo("#s06-watch", { scale: 1.08 }, { scale: 1, duration: 0.6, ease: "elastic.out(1, 0.5)", immediateRender: false }, C.drop);
  tl.fromTo("#s06-glow", { opacity: 0 }, { opacity: 1, duration: 0.08 }, C.drop);
  tl.to("#s06-glow", { opacity: 0.3, duration: 1.2, ease: "power2.out" }, C.drop + 0.1);
  ripple("#s06-tap2", C.why_tap, 0.45);
  tl.fromTo("#s06-w-why", { opacity: 0, clipPath: "inset(0% 0% 72% 0%)" }, { opacity: 1, duration: 0.15 }, C.why_tap + 0.25);
  tl.to("#s06-w-checkin", { opacity: 0, duration: 0.15 }, C.why_tap + 0.25);
  C.why_layers.forEach((t, i) => tl.to("#s06-w-why", { clipPath: `inset(0% 0% ${[58, 44, 30, 0][i]}% 0%)`, duration: 0.2, ease: "power2.out" }, t));
  // Quiet hours sound and look muffled.
  tl.fromTo("#s06-night", { opacity: 0 }, { opacity: 1, duration: 2.0, ease: "power1.inOut" }, 28.0);
  tl.to("#s06-night", { opacity: 0, duration: 0.12 }, C.drop);
  // The real decision for each hour, under the watch.
  const iHeld = night.findIndex((r) => r.code === "QUIET_HOURS_HELD");
  const iSent = night.findIndex((r) => r.code === "SENT_CHECK_IN");
  const iStart = Math.max(0, night.findIndex((r) => r.t === "22:50"));
  const quiet = night.slice(iStart, iHeld), between = night.slice(iHeld + 1, iSent);
  const timed = [];
  quiet.forEach((r, i) => timed.push([C.night_ticks[0] + (i * (C.night_ticks[C.night_ticks.length - 1] - C.night_ticks[0])) / Math.max(quiet.length - 1, 1), r]));
  timed.push([C.held, night[iHeld]]);
  between.forEach((r, i) => timed.push([C.same_story[0] + i * 0.5, r]));
  timed.push([C.drop, night[iSent]]);
  const dlBox = $("#s06-log");
  timed.forEach(([t, r], i) => {
    const kind = r.outcome === "sent" ? "sent" : r.outcome === "held" ? "held" : "";
    const d = el("div", `dl ${kind}`, `${r.t} · ${r.reason.replace(/\.$/, "")}<span class="code">${r.code}</span>`);
    dlBox.appendChild(d);
    tl.fromTo(d, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.15, ease: IN }, t);
    const next = timed[i + 1];
    if (next) tl.to(d, { opacity: 0, duration: 0.08 }, next[0] - 0.08);
    else tl.to(d, { opacity: 0, duration: 0.15 }, C.why_tap);
  });
  const caps = [
    [C.night_ticks[0], "Every hour, it checks.<br><span class=\"soft\">Nothing unusual.</span>"],
    [C.held, `${ampm(night[iHeld].t)}: the air turns bad.<br><span class="soft">But it's quiet hours.</span>`],
    [C.same_story[0], "So it holds the message.<br><span class=\"soft\">No 5am buzz.</span>"],
    [C.drop, `${ampm(night[iSent].t)}: one message,<br><span class="accent">at his check-in.</span>`],
    [C.why_tap, "Tap why.<br><span class=\"soft\">It explains itself.</span>"],
  ];
  const capBox = $("#s06-caps");
  caps.forEach(([t, html], i) => {
    const c = el("div", "cap", html);
    capBox.appendChild(c);
    show(c, t, { dy: 24, d: 0.35, out: caps[i + 1] ? caps[i + 1][0] : undefined });
  });

  /* ---------- 7 · proof ---------- */
  tl.fromTo(".top-eyebrow", { opacity: 0 }, { opacity: 1, duration: 0.3 }, C.proof_cards[0]);
  ["#s07-card0", "#s07-card1", "#s07-card2"].forEach((c, i) => {
    tl.fromTo(c, { opacity: 0, y: 70 }, { opacity: 1, y: 0, duration: 0.35, ease: IN }, C.proof_cards[i]);
    if (i < 2) tl.to(c, { opacity: 0, y: -40, duration: 0.15, ease: "power2.in" }, C.proof_cards[i + 1] - 0.15);
  });
  const spark = $("#s07-spark"), vmax = Math.max(...D.mumbai.map((m) => m.v));
  D.mumbai.forEach((m, i) => {
    const h = Math.max(8, (m.v / vmax) * 470);
    const glitch = m.v === vmax;
    const sp = el("div", `sp${glitch ? " glitch" : ""}`, `<div class="col" style="height:${h}px"></div><div class="v" style="bottom:${h + 84}px">${m.v}</div><div class="t">${m.t}</div>`);
    spark.appendChild(sp);
    tl.fromTo(sp.querySelector(".col"), { scaleY: 0 }, { scaleY: 1, duration: glitch ? 0.25 : 0.35, ease: glitch ? "power4.out" : IN }, C.proof_cards[0] + 0.15 + i * 0.1);
    tl.fromTo(sp.querySelector(".v"), { opacity: 0 }, { opacity: 1, duration: 0.15 }, C.proof_cards[0] + 0.3 + i * 0.1);
    if (glitch) tl.to(sp.querySelector(".col"), { backgroundColor: "#3a3a3c", duration: 0.2 }, C.glitch_stamp + 0.1);
  });
  $("#s07-note0").textContent = `Mumbai, ${D.mumbai_day}. The data source didn't flag it.`;
  tl.fromTo("#s07-stamp", { opacity: 0, scale: 2.2, rotation: -9 }, { opacity: 1, scale: 1, rotation: -9, duration: 0.22, ease: "back.out(2.2)" }, C.glitch_stamp);
  tl.fromTo("#s07-note0", { opacity: 0 }, { opacity: 1, duration: 0.3 }, C.glitch_stamp + 0.1);
  // Alerts a week, per person, from the replay: one person per city.
  const people = [];
  D.cities.forEach((c) => {
    const ps = D.replay.weekly.filter((w) => w.city === c.city);
    const p = ps.find((w) => w.sensitivity === "default") ?? ps[0];
    if (p) people.push(p);
  });
  const lo = Math.min(...people.map((p) => p.events_per_week)), hi = Math.max(...people.map((p) => p.events_per_week));
  $("#s07-rate").innerHTML = `<span class="accent">${lo}–${hi}</span> alerts<br>a week.`;
  const rates = $("#s07-rates"), rmax = Math.max(hi, 3);
  people.forEach((p, i) => {
    const name = p.user[0].toUpperCase() + p.user.slice(1);
    const r = el("div", "rate", `<span class="name">${p.city}</span><span class="who">${name}${p.sensitivity === "default" ? "" : ", " + p.sensitivity + " sensitivity"}</span>
      <div class="track"><div class="bar" style="width:100%"></div></div><div class="num">${p.events_per_week}</div>`);
    rates.appendChild(r);
    tl.fromTo(r.querySelector(".bar"), { scaleX: 0 }, { scaleX: p.events_per_week / rmax, duration: 0.4, ease: IN }, C.proof_cards[1] + 0.2 + i * 0.1);
  });
  tl.fromTo("#s07-card2 .mega", { scale: 1.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: POP }, C.proof_cards[2]);
  ["#s07-flat", "#s07-x1", "#s07-x2", "#s07-rise"].forEach((s, i) => {
    const p = $(s), len = p.getTotalLength();
    p.style.strokeDasharray = `${len}`;
    tl.fromTo(p, { strokeDashoffset: len }, { strokeDashoffset: 0, duration: [0.45, 0.12, 0.12, 0.4][i], ease: "power2.out" }, C.proof_cards[2] + [0.2, 0.75, 0.88, 1.1][i]);
  });
  tl.to("#s07-flat", { opacity: 0.35, duration: 0.2 }, C.proof_cards[2] + 1.0);
  tl.fromTo("#s07-fix", { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.3, ease: IN }, C.proof_cards[2] + 1.3);

  /* ---------- 8 · every silence has a reason ---------- */
  show("#s08-h1", C.log_rows_start);
  show("#s08-h2", C.log_line2);
  const LABEL = { sent: "sent", held: "held", suppressed: "suppressed", no_event: "quiet" };
  const logRows = night.slice(iStart, iStart + 16);
  const box = $("#s08-rows");
  let focusIndex = 0;
  logRows.forEach((r, i) => {
    const row = el("div", `lrow ${r.outcome}`, `<span class="t">${r.t}</span><span class="dot"></span><span class="o">${LABEL[r.outcome] ?? r.outcome}</span><span class="c">${r.code}</span>`);
    if (r.code === "SENT_CHECK_IN") focusIndex = i;
    box.appendChild(row);
    tl.fromTo(row, { opacity: 0, x: 40 }, { opacity: 1, x: 0, duration: 0.2, ease: IN }, C.log_rows_start + i * C.log_rows_step);
  });
  const rowsEls = [...box.children];
  const focusY = focusIndex * 66 + 28;
  tl.to(rowsEls.filter((_, i) => i !== focusIndex), { opacity: 0.18, duration: 0.3 }, C.log_push);
  tl.to(rowsEls[focusIndex], { backgroundColor: "#2a1a0e", boxShadow: "0 0 0 3px #ff7a1a", duration: 0.2 }, C.log_push);
  tl.fromTo("#s08-rows", { scale: 1, transformOrigin: `0px ${focusY}px` }, { scale: 1.5, duration: 0.5, ease: "power3.inOut" }, C.log_push);
  // Three lines of the real trace behind the 06:30 message.
  const tv = (layer, pred) => (W.trace.find((t) => t.layer === layer && (!pred || pred(t.values))) || {}).values || {};
  const d2 = tv("D2"), d8 = tv("D8", (v) => "absorbed_held" in v || "check_in" in v), d7 = tv("D7");
  const local = (iso) => { if (!iso) return null; const d = new Date(iso); const ist = new Date(d.getTime() + 5.5 * 3600e3); return ampm(`${ist.getUTCHours()}:${String(ist.getUTCMinutes()).padStart(2, "0")}`); };
  const lines = [
    ["D2", d2.started_at ? `Same story since ${local(d2.started_at)}, peak ${d2.peak?.pm25 ?? "?"} µg/m³.` : "Same story, still open."],
    ["D8", `Check-in at ${typeof d8.check_in === "string" ? d8.check_in : night[iSent].t}: ${BAND[d8.band] ?? "bad air"}, worse than usual. Absorbs ${d8.absorbed_held ?? 1} held notice.`],
    ["D7", `${d7.sent_today ?? 0} of ${d7.max_per_day ?? 3} messages used today. Send.`],
  ];
  const tr = $("#s08-trace");
  lines.forEach(([layer, text], i) => {
    const l = el("div", "tl", `<span class="layer">${layer}</span>${text}`);
    tr.appendChild(l);
    tl.fromTo(l, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.25, ease: IN }, C.log_trace_lines[i]);
  });

  /* ---------- 9 · built to grow ---------- */
  show("#s09-h1", C.layer_tiles[0]);
  show("#s09-h2", C.future_icons[0]);
  const PLANES = [
    ["Sense", [["S1", "real", "pollen"], ["S2", "real"], ["S3", "stub"]]],
    ["Understand", [["U1", "real"], ["U2", "real"], ["U3", "none", "heart"]]],
    ["Decide", [["D1", "real"], ["D2", "real"], ["D3", "real"], ["D4", "real"], ["D5", "stub"], ["D6", "stub", "sos"], ["D7", "stub"], ["D8", "real"]]],
    ["Act", [["A1", "real"], ["A2", "stub"]]],
    ["Learn", [["L1", "real"], ["L2", "stub"]]],
  ];
  const ICON = {
    pollen: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="4.5" r="2.2"/><circle cx="12" cy="19.5" r="2.2"/><circle cx="4.5" cy="12" r="2.2"/><circle cx="19.5" cy="12" r="2.2"/></svg>',
    heart: '<svg viewBox="0 0 24 24"><path d="M2 12h4l2-5 4 10 2-5h8"/></svg>',
    sos: '<svg viewBox="0 0 24 24"><path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z"/><path d="M12 8v5M12 16v.5"/></svg>',
  };
  const grid = $("#s09-grid");
  const tiles = [], stubs = [], badges = [];
  PLANES.forEach(([name, ls]) => {
    const p = el("div", "plane", `<div class="pn">${name}</div><div class="tiles"></div>`);
    grid.appendChild(p);
    ls.forEach(([id, kind, icon]) => {
      const t = el("div", `tile ${kind}`, id);
      if (icon) { const b = el("div", "badge", ICON[icon]); t.appendChild(b); badges.push(b); }
      p.querySelector(".tiles").appendChild(t);
      tiles.push(t);
      if (kind === "stub") stubs.push(t);
    });
  });
  tl.fromTo(".plane .pn", { opacity: 0 }, { opacity: 1, duration: 0.3 }, C.layer_tiles[0]);
  tiles.forEach((t, i) => tl.fromTo(t, { opacity: 0, scale: 0.7 }, { opacity: 1, scale: 1, duration: 0.25, ease: POP }, C.layer_tiles[0] + (i * (C.layer_tiles[1] - C.layer_tiles[0])) / tiles.length));
  tl.to(stubs, { borderColor: "#ffb340", color: "#ffb340", backgroundColor: "rgba(255,179,64,0.12)", duration: 0.3 }, C.stubs_amber);
  badges.forEach((b, i) => tl.fromTo(b, { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2.5)" }, C.future_icons[i]));
  tl.fromTo(".legend", { opacity: 0 }, { opacity: 1, duration: 0.3 }, C.layer_tiles[0] + 0.5);

  /* ---------- 10 · end ---------- */
  tl.fromTo("#s10-l1", { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.5, ease: IN }, C.end_lines[0]);
  tl.fromTo("#s10-l2", { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.5, ease: IN }, C.end_lines[1]);
  tl.fromTo("#s10-brand", { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.6, ease: IN }, C.end_repo);
  tl.fromTo("#s10-fade", { opacity: 0 }, { opacity: 1, duration: 0.5, ease: "power1.in" }, 59.45);

  return tl;
};
