// Capture the real watch demo at chosen replayed moments, as crisp PNGs for the composition.
//
// Start the watch demo first (it serves fixtures from the real replay), then:
//   node docs/demo/video/scripts/capture_watch.mjs [http://127.0.0.1:8100]
//
// Uses the system Chrome that HyperFrames renders with. Writes composition/assets/watch/*.png
// (the watch only, transparent outside the bezel) and chips.png (the scenario chip row).
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const video = join(here, "..");
const out = join(video, "composition", "assets", "watch");
mkdirSync(out, { recursive: true });
const base = process.argv[2] ?? "http://127.0.0.1:8100";

// The night's moments come from the extracted data, so the shots follow the real replay.
const dataJs = readFileSync(join(video, "composition", "assets", "data.js"), "utf8");
const DATA = JSON.parse(dataJs.slice(dataJs.indexOf("=") + 1).trim().replace(/;$/, ""));
const night = DATA.watch.night_utc;
const at = (code) => night.find((r) => r.code === code)?.utc;
// A quiet evening hour a few hours into the window, so the watch has some history to summarise.
const evening = night[Math.max(0, DATA.watch.night.findIndex((r) => r.t === "22:50"))].utc;

const shots = [
  { name: "01-evening", path: `/?scenario=delhi-smog-night&t=${evening}` },
  { name: "02-held", path: `/?scenario=delhi-smog-night&t=${at("QUIET_HOURS_HELD")}` },
  { name: "03-checkin", path: `/?scenario=delhi-smog-night&t=${at("SENT_CHECK_IN")}` },
  { name: "04-why", path: `/why/${DATA.watch.check_in.id}?scenario=delhi-smog-night&t=${at("SENT_CHECK_IN")}` },
  { name: "05-cleared", path: `/?scenario=delhi-smog-night` },
  { name: "06-glitch", path: `/?scenario=glitch-ignored` },
  { name: "07-calm", path: `/?scenario=back-to-normal` },
];
// Every quiet hour before the held notice, so the watch ticks through the real night.
const iStart = Math.max(0, DATA.watch.night.findIndex((r) => r.t === "22:50"));
const iHeld = night.findIndex((r) => r.code === "QUIET_HOURS_HELD");
for (let i = iStart; i < iHeld; i++) {
  shots.push({ name: `night-${DATA.watch.night[i].t.replace(":", "")}`, path: `/?scenario=delhi-smog-night&t=${night[i].utc}` });
}

const chrome = execFileSync("npx", ["hyperframes", "browser", "path"], { cwd: video, encoding: "utf8" })
  .trim().split("\n").pop();
const browser = await puppeteer.launch({ executablePath: chrome, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 900, height: 900, deviceScaleFactor: 3 });
for (const s of shots) {
  await page.goto(base + s.path, { waitUntil: "networkidle0" });
  await page.addStyleTag({ content: "*{animation:none!important;transition:none!important} body{background:transparent!important}" });
  await page.evaluate(() => document.fonts.ready);
  const watch = await page.$(".watch");
  await watch.screenshot({ path: join(out, `${s.name}.png`), omitBackground: true });
  if (s.name === "01-evening") {
    const chips = await page.$(".chips");
    if (chips) await chips.screenshot({ path: join(out, "chips.png"), omitBackground: true });
  }
  console.log("captured", s.name, s.path);
}
await browser.close();
