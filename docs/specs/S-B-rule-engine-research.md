# S-B — Rule engine research

Status: research input for S-C · 2026-10-18 · Feeds FR-DET, FR-SENS, FR-RULE, FR-DEDUP, FR-OBS, FR-EVAL

> This is the research as gathered, kept for its sources and reasoning. Where it differs from the final design, the closed [explainer](../explainer.md) and [S-C](S-C-rule-engine-spec.md) win. The main differences: "trend" became **climb** (it must be rising), "drift" became **elevated**, inhibition became the **ARBITRATE** layer, the daily cap became the **BUDGET** layer, and the CUSUM bar is 8, not 5.

Claims were checked against official docs or package metadata on 2026-10-18. Anything marked **[unverified]** could not be confirmed from a primary source.

---

## Executive summary

| Area | Recommendation |
|---|---|
| 1. Alerting semantics | **Copy the state machine, not the infrastructure.** Use Grafana's states (Normal → Pending → Alerting → Recovering, plus NoData), with Prometheus `for` as persistence and `keep_firing_for` as exit hysteresis. A PagerDuty-style `dedup_key` becomes the episode key. Alertmanager inhibition becomes "severe inhibits minor". Datadog's renotify interval, cap and escalation message become cooldown. Nagios high/low thresholds stop flapping. Quiet hours are `mute_time_intervals` that **hold and release** instead of dropping. |
| 2. AQI standard | **US EPA AQI (2024 breakpoints) applied to NowCast PM2.5** for severity bands and floors. Detection runs on raw hourly values. CPCB NAQI is a 24h index (16h minimum data), so it's unfit for hourly nudges. At most it's a secondary label. |
| 3. Rule engine | **Hand-roll a tiny typed evaluator.** User rules are a fixed set of dials run as an ordered pipeline of pure functions. Each returns `(outcome, reason)`. No library models hold-and-release, cooldown or episodes. Borrow the `all`/`any` JSON shape from `business-rules`. Keep `rule-engine` as a future escape hatch for free-form conditions. |
| 4. Detector | **Hour-of-day robust baseline (median/MAD, trailing 14 days) → robust z → three cheap statistics:** confirmed z for spikes, EWMA for trends and one-sided CUSUM for slow drift. Recovery uses hysteresis. Recompute from a fixed lookback every tick, so late data and replay are deterministic. Standard library only. `ruptures` is used **only in the eval harness** as an independent labeller. Skip river, Kats, Merlion, PyOD and changefinder. |

---

## 1. Industry monitoring and alerting semantics

### 1.1 What each system does (verified)

**Prometheus rules.** With `for`, an alert stays **pending** until the condition holds on every evaluation for the duration, then **fires**. `keep_firing_for` keeps it firing after the condition was last met. The docs say this helps with flapping and with false resolutions from missing data. Labels identify an alert. Annotations describe it.

**Alertmanager.**
- `group_by` batches alerts into groups.
- `group_wait` (default 30s) delays a new group's first notification.
- `group_interval` (default 5m) re-sends only when a group has new firing or resolved alerts.
- `repeat_interval` (default 4h) re-sends an unchanged group.
- **Inhibition** mutes `target_matchers` alerts while a `source_matchers` alert fires, if the `equal` labels match.
- **Silences** are manual, time-bound label mutes.
- `mute_time_intervals` sends nothing inside a scheduled window (UTC by default).

**Grafana.** Instance states are Normal, Pending, Alerting and **Recovering**, which is the keep-firing window. A re-breach while Recovering returns to Alerting **without a new notification**. **NoData** is a successful query with no points. **Error** is a failed evaluation. Each rule maps them to NoData/Error, Alerting, Normal or **Keep last state**. The docs warn that Keep last state is unsuitable for strict monitoring.

**Datadog.** There are three anomaly algorithms:
- **basic:** rolling quantile, no seasonality.
- **agile:** a robust SARIMA variant that adapts fast to level shifts.
- **robust:** seasonal-trend decomposition, stable through long anomalies.

Seasonal algorithms need **at least 3× the seasonal period** of history. Trigger and recovery windows are a *fraction of anomalous points*, and **recovery thresholds** can be set separately from alert thresholds. No-data options are notify, zero, last known status or OK. **Renotify** has an interval, a status filter, a **max occurrences** cap and an **escalation message**.

**PagerDuty.** A `trigger` carrying an open alert's `dedup_key` attaches to that alert. After `resolve`, the same key opens a **new** alert. Severities are info, warning, error and critical. Intelligent grouping uses a rolling window that extends with each alert, up to 24h. I didn't retrieve the time-based grouping defaults **[unverified]**.

**Nagios / Icinga.** Flapping is a recency-weighted percent state change over about 20 transitions. An object starts flapping above the high threshold and stops only below the low one. Icinga's defaults are 30% and 25%. While an object flaps, normal notifications are suppressed and only FlappingStart and FlappingEnd are sent.

### 1.2 Mapping and verdicts

| Concept | Maps to our need | Verdict |
|---|---|---|
| `for` / Pending | FR-DET-5 persistence before an episode opens | **Adopt.** 2 of the last 3 hours for spikes, 3 consecutive hours for trends. |
| `keep_firing_for` / Recovering | Return to normal (FR-DET-4) without flapping. A re-breach rejoins silently. | **Adopt.** 3h dwell before a recovery notice. |
| Separate recovery threshold | Hysteresis: high entry bar, low exit bar | **Adopt.** |
| Labels vs annotations | Identity fields vs evidence fields in the decision log | **Adopt.** |
| `group_by` | Episode key = (user, station, pollutant) | **Adopt.** |
| `group_wait` | Already covered by `for` | **Skip.** |
| `group_interval` "only on change" | Speak again only on a meaningful change (FR-DEDUP-3) | **Adopt.** This is the core dedup rule. |
| `repeat_interval` | Re-notify an unchanged episode | **Adapt.** Off by default. At most one "still bad" line, at the next check-in. |
| Inhibition with `equal` | Severe inhibits minor for the same (user, station). An open trend inhibits a spike notice unless the band escalates. | **Adopt** as a fixed precedence list. |
| Silences | User snooze | **Adapt later.** Same mechanism as quiet hours. |
| `mute_time_intervals` | Quiet hours. But Alertmanager *drops*. We must **hold and release** (FR-RULE-2), and let severe break through. | **Adapt.** Interval + hold queue + severity bypass. |
| Routing tree / `continue` | Multi-channel routing | **Skip.** v1 has one action. |
| NoData / Keep last state | Polling gaps (FR-ING-3, FR-DET-6) | **Adopt.** Keep last state for up to 3h, then NoData. NoData never opens or closes an episode. |
| `dedup_key` lifecycle | Episode ID. Triggers append to the open episode; a new one starts after close. | **Adopt.** `episode_id = hash(user, station, pollutant, opened_at)`. |
| Renotify cap + escalation message | Cooldown and decay (FR-DEDUP-4). The escalation message is our "this got worse" notice. | **Adopt.** Cooldown + per-episode cap + severe override. |
| Flap detection (high/low) | Episodes that open and close repeatedly | **Adapt, simplified.** A return within 6h of closing reopens the *same* episode. Weighted percentages are overkill at 24 ticks a day. |
| Datadog robust / 3× history | Baseline design (section 4) | **Borrow.** A seasonal profile that doesn't chase anomalies, trusted after 3 days of history. |

---

## 2. Consumer air quality and health alerting prior art

| Product | Pattern | Lesson for us |
|---|---|---|
| **EPA EnviroFlash** | The user picks an AQI threshold. Agencies suggest a lower one, such as Moderate, for sensitive people. Forecast emails go out the day before. Some agencies add realtime alerts when a monitor exceeds the threshold. | A per-user, sensitivity-based threshold and a fixed daily send time. No memory, no baseline. |
| **IQAir / AirVisual** | Threshold notifications, plus a daily notification at a chosen time **[unverified: retail-site blog, not official help]** | The same two primitives as our quiet-hours and check-in pair |
| **PurpleAir** | I found no official native alert docs **[unverified]**. Third parties such as Watch Duty offer per-sensor AQI thresholds. Community threads ask for "sustained hour" and rate-of-rise alerts. | Users ask for persistence and rate of change, which is what our detector provides |
| **Apple Watch heart rate** | User-set bpm threshold. It fires when heart rate "remains" past the threshold after at least 10 minutes of inactivity. The persistence duration isn't defined **[unverified]**. | Threshold + persistence + a **context gate**. Ours are quiet hours and the check-in window. |

**Takeaway.** Consumer prior art is fixed thresholds plus a daily digest. What sets us apart is the baseline-relative detector, episode memory and explanations. Absolute floors (FR-SENS-3) mirror EnviroFlash's sensitivity thresholds.

**NowCast (EPA PM2.5, from AirNow).**
1. Take the last 12 hourly values.
2. w = 1 − (max − min)/max, clamped to [0.5, 1]. The floor of 0.5 approximates a 3-hour average.
3. NowCast = Σ wⁱcᵢ / Σ wⁱ, where i is hours ago.
4. It's valid only if 2 of the 3 most recent hours are valid.
5. Truncate to 0.1 µg/m³, then convert to AQI.

Missing hours appear to be dropped from both sums, judging by AirNow's worked example **[unverified as a stated rule]**. Even at w = 0.5, NowCast lags a real spike. So use it for **severity bands and messages**, and run **spike detection on raw hourly values**.

**US EPA PM2.5 AQI, 2024 revision** (40 CFR 58 App. G, Table 2; 24h µg/m³, truncated to 1 decimal place):

| AQI | Category | PM2.5 |
|---|---|---|
| 0–50 | Good | 0.0–9.0 |
| 51–100 | Moderate | 9.1–35.4 |
| 101–150 | Unhealthy for Sensitive Groups | 35.5–55.4 |
| 151–200 | Unhealthy | 55.5–125.4 |
| 201–300 | Very Unhealthy | 125.5–225.4 |
| 301+ | Hazardous | 225.5+ |

**India CPCB NAQI** (Govt. of India IES reference; matches the 2014 launch tables, so revisions since then weren't checked **[unverified]**):
- PM2.5 (24h): Good 0–30, Satisfactory 31–60, Moderate 61–90, Poor 91–120, Very Poor 121–250, Severe 250+.
- Averaging is 24h for PM, NO2, SO2, NH3 and Pb, and 8h for O3 and CO.
- Each sub-index needs 16 hours of data. The overall index needs 3 or more pollutants, including PM, and takes the worst sub-index.

**Which standard?** **EPA + NowCast.** It's built for hourly reporting. It's stricter at the low end (Good ends at 9, vs 30), which suits a health-sensitive product. And it gives one scale across all cities. CPCB is a daily index by design, so hourly use would hide spikes and delay recovery news. S-A owns the final call. CPCB labels can appear as secondary text for Indian users.

---

## 3. Open-source rule engines and formats (Python)

| Library | Latest release / status | Rule expression | Fit | Verdict |
|---|---|---|---|---|
| **rule-engine** (zeroSteiner) | 5.0.2, Jul 2026, active. One dep (python-dateutil). | Strings like `pm25 > 35 and city == "Delhi"`, with datetime and timedelta types. `Rule(text).matches(dict)`. | Good free-form predicates. No time windows, holds or state. | **Skip for v1.** Escape hatch for a future `extra_condition`. |
| **business-rules** (venmo) | 1.1.1, Mar 2022. `six`, Python 2 era. | JSON `conditions: {all/any: [{name, operator, value}]}` + `actions`. Variables are declared in code. | Ideal shape for UI or learning-layer edits (FR-RULE-5). The package is stale. | **Borrow the format, skip the package.** |
| **durable_rules** | PyPI 2.0.28, Jun 2020. C core, Rete. | `@when_all` decorators over events and facts | Rules are *code*, which conflicts with FR-RULE-5. Native build. | **Skip.** |
| **JsonLogic** | Ports: json-logic 0.6.3 (2015), panzi-json-logic 1.0.1 (2021) | `{"and": [{"<": [{"var": "temp"}, 110]}]}`. Data-only, side-effect free. | Nice format, but the ports are unmaintained and it's verbose | **Skip.** |
| **CEL** (cel-python) | 0.5.0, Jan 2026, active. Deps: lark, google-re2, pendulum, pyyaml, jmespath. | `a.balance >= tx.amount`; compile → program → evaluate | Safe and standard. Heavy dependencies and non-Python numeric semantics. | **Skip.** |
| **GoRules ZEN** (zen-engine) | 2.1.3, Oct 2026, active. Rust core, native wheels. | JSON decision graphs and tables. `evaluate(key, input)` with trace. | Powerful, but heavyweight and opaque, with no temporal state | **Skip.** Revisit if non-engineers author rules. |

**Recommendation: hand-roll.** Our rules aren't arbitrary predicates. They are a small, fixed vocabulary of dials, and the hard parts are *temporal and stateful*:
- holding during quiet hours and releasing at the end
- severe breakthrough
- a check-in compared against the norm for that hour
- cooldown decay
- episode memory

A generic engine would only cover the snapshot predicate and add a second, less explainable layer. A typed schema (dataclasses or pydantic) plus an ordered pipeline of pure functions gives deterministic replay (time is injected), one log entry with a reason code per step (FR-RULE-6), and zero new dependencies.

Fixed precedence for S-C:
1. Data-quality gate.
2. Geo match.
3. Pollutant filter.
4. Sensitivity-adjusted detector threshold, OR the absolute floor.
5. Inhibition.
6. Episode and meaningful change.
7. Cooldown (severe overrides).
8. Quiet hours (hold unless severe).
9. Emit.

Rules are stored as JSON or YAML.

---

## 4. Lightweight learned anomaly and change-point methods

| Method / library | Online? | Fits hourly per station? | Explainable? | Deps | Maintenance | Verdict |
|---|---|---|---|---|---|---|
| Robust z (median/MAD) | Yes | Yes. Robust to past spikes. | Very ("well above the usual for 7pm") | stdlib | n/a | **Adopt** as the score |
| Hour-of-day profile | Yes | Yes. Captures diurnal peaks. | Very | stdlib | n/a | **Adopt** as the baseline |
| STL | Offline | Nightly refit only | Medium | statsmodels | Active | **Skip.** The hour-of-day median is the poor man's STL. |
| EWMA chart | Yes | Yes. NIST: for small or gradual shifts, λ 0.2–0.3, limits ±k·s·√(λ/(2−λ)) | High | stdlib | n/a | **Adopt** for trend and recovery |
| One-sided CUSUM | Yes | Yes. NIST: efficient for shifts ≤2σ, k ≈ δ/2, h ≈ 4–5 | High ("excess building for 9h") | stdlib | n/a | **Adopt** for slow drift |
| BOCPD (Adams & MacKay 2007) | Yes, exact run-length posterior | Yes | Medium | ~80 lines of numpy. The `bocd` package dates from 2019. | Paper | **Skip v1.** v2 or harness comparator. |
| ruptures | **Offline** | No | Medium | numpy, scipy | Active (1.1.10, Sep 2025) | **Adapt.** PELT as the harness reference labeller. |
| river ADWIN | Yes | Checks every 32 points by default. Reports change, not direction or magnitude. | Low–medium | numpy, scipy, narwhals; Python ≥3.11 | Active (0.26.1) | **Skip** |
| river HalfSpaceTrees | Yes | Poor. Docs say it struggles with clustered anomalies, which is what episodes are. Randomised, needs scaling. | Low | same | Active | **Skip** |
| changefinder | Yes | Yes | Low | small | 0.03, 2014, dead | **Skip** |
| Kats | Mixed | Has CUSUM | Medium | Pins numpy<1.22, pandas≤1.3.5, fbprophet, pystan | 0.2.0, Mar 2022 | **Skip.** Won't install on a modern stack. |
| Merlion | Mixed | Yes | Medium | Heavy | **Archived Mar 2026** | **Skip** |
| PyOD | Batch, multivariate | Overkill | Low | sklearn, numba | Active | **Skip** |

### 4.1 Recommended v1 detector, per station and pollutant

**Transform.** Use `y = log1p(PM2.5)`. It tames right skew and makes "doubling" comparable between clean and dusty cities.

**Data-quality gate.** Drop readings that are negative, above a sanity cap, or stuck (identical for 6 or more hours). Flag a single-hour jump that fully reverts the next hour as `dq_suspect`: logged, not scored.

**Baseline.** For each hour of day h, `m_h` = the median and `s_h` = 1.4826·MAD of y over the trailing 14 days.
- Shrink toward the all-hours median and MAD while an hour has fewer than 7 samples.
- Use the all-hours baseline only until 3 days of history exist.
- Floor `s_h`, so flat, clean stations don't fire on noise.

**Score.** `z = (y − m_h) / s_h`. This gives per-station sensitivity by construction (FR-SENS-1). Per-user sensitivity scales the thresholds (FR-SENS-2). For example, a sensitive user gets ×0.75.

**Spike.**
- z ≥ 3.5, and z rose by at least 2 since the previous hour.
- Confirmed when 2 of the last 3 hours meet the threshold.
- If the NowCast band is Very Unhealthy or worse, open on the first DQ-clean reading.

**Sustained trend.**
- EWMA(z) with λ = 0.3 exceeds 3·√(λ/(2−λ)) ≈ 1.26.
- AND the Theil–Sen slope of y over 6h is positive.
- AND both hold for 3 consecutive hours.

**Slow-burn drift (FR-DET-6).** An upper CUSUM on z, with k = 0.5 and h = 5, catches days stuck at z ≈ 1–2 that never trip the other checks. Log near-misses at CUSUM > 0.8h, or z ≥ 0.8 × the spike bar.

**Return to normal.**
- EWMA(z) < 1.0, AND the NowCast band is at or below the user's floor.
- Holds for 3 consecutive hours.
- CUSUM then resets. A re-breach within 6h reopens the same episode.

**Seasonality** is handled by the hour-of-day profile. Weekday/weekend profiles are a v2 item.

**Absolute floors** are a guard rail, not a detector. A NowCast band at or above the user's floor makes an event eligible even when z is normal. That covers the "normal for Delhi, still unhealthy" case.

**Determinism.** Persist no incremental EWMA or CUSUM state. Each tick recomputes everything from readings known at that tick: the baseline over 14 days, and EWMA and CUSUM from zero over 72h. Replay then equals live (FR-EVAL-5). Late, back-filled and post-gap readings are re-evaluated for free (FR-DET-6). At 5 stations × 24 ticks, the cost is negligible.

**Harness.** `ruptures` PELT (l2 cost on y) over full history, plus a few hand labels, forms the reference set of "interesting moments". It's independent of the live detector, so the harness isn't grading the detector against itself.

---

## 5. Concepts we'll borrow (glossary)

| Industry term | Source | Our term | Meaning here |
|---|---|---|---|
| Alert instance / `group_by` / `dedup_key` | Alertmanager, PagerDuty | **Episode** | A bad period for (user, station, pollutant): opened, evolving, closed. A new one starts after close. |
| Pending + `for` | Prometheus, Grafana | **Confirmation** | k of N hours anomalous before an episode opens |
| Recovering / `keep_firing_for` / recovery threshold | Grafana, Prometheus, Datadog | **Recovery dwell (hysteresis)** | A lower exit bar held for M hours. A re-breach rejoins silently. |
| `group_interval` "only on change" | Alertmanager | **Meaningful change** | Speak only on open, band escalation, a new event kind, or recovery |
| Renotify interval + cap + escalation | Datadog | **Cooldown / decay** | A minimum gap that relaxes over time, a per-episode cap, and a severe bypass |
| Inhibition rule | Alertmanager | **Inhibition** | A worse or broader active event mutes lesser ones for the same user and station |
| Silence / `mute_time_intervals` | Alertmanager | **Silence / quiet hours** | A window where non-severe output is *held* and released, not dropped |
| NoData / Keep last state | Grafana, Datadog | **No-data** | A gap of 3h or less keeps state. Beyond that, NoData is logged and changes no episode. The gap is re-evaluated when data returns. |
| Flapping | Nagios, Icinga | **Flap guard** | A return within 6h reuses the episode, with no premature "back to normal" |
| Labels vs annotations | Prometheus | **Identity vs evidence** | Decision-log fields that key a decision vs fields that explain it |
| Anomaly bounds / seasonality | Datadog | **Baseline band** | Per-station hour-of-day median ± z·MAD |

---

## Sources

- Prometheus alerting rules: https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- Alertmanager configuration: https://prometheus.io/docs/alerting/latest/configuration/
- Alertmanager concepts: https://prometheus.io/docs/alerting/latest/alertmanager/
- Grafana state and health: https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/state-and-health/
- Grafana alert rule evaluation: https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/
- Grafana Recovering state: https://grafana.com/whats-new/2025-05-05-grafana-managed-alert-rule--recovering--state/
- Datadog anomaly monitor: https://docs.datadoghq.com/monitors/types/anomaly/
- Datadog monitor configuration: https://docs.datadoghq.com/monitors/configuration/
- Datadog notifications / renotify: https://docs.datadoghq.com/monitors/notify/
- PagerDuty Events API v2 overview: https://docs.pagerduty.com/developer/events-api-v2-overview
- PagerDuty send alert event (dedup): https://docs.pagerduty.com/developer/send-alert-event
- PagerDuty alert grouping: https://support.pagerduty.com/docs/content-based-alert-grouping , https://support.pagerduty.com/docs/intelligent-alert-grouping
- Nagios flapping: https://assets.nagios.com/downloads/nagioscore/docs/nagioscore/4/en/flapping.html
- Icinga 2 flapping: https://icinga.com/docs/icinga-2/latest/doc/08-advanced-topics/
- AirNow NowCast: https://forum.airnowtech.org/t/the-nowcast-for-pm2-5-and-pm10/172
- MPCA NowCast formula: https://www.pca.state.mn.us/sites/default/files/nowcast-formula.pdf
- 40 CFR 58 Appendix G: https://www.law.cornell.edu/cfr/text/40/appendix-G_to_part_58
- EPA 2024 PM AQI fact sheet: https://www.epa.gov/system/files/documents/2024-02/pm-naaqs-air-quality-index-fact-sheet.pdf
- NC DEQ 2024 PM2.5 standard: https://www.deq.nc.gov/about/divisions/air-quality/air-quality-planning/attainment/2024-pm25-annual-standard
- India NAQI (IES Arthapedia): https://ies.gov.in/arthapedia/concept/national-air-quality-index
- EnviroFlash (Maine DEP): https://www.maine.gov/dep/air/ozone/enviroflash.html
- EPA New England alert program: https://www.epa.gov/AQNE/air-quality-alert-program-new-england
- IQAir notifications (retail blog): https://shop.iqair.cn/blogs/news/how-to-change-notifications-on-airvisual-app
- Watch Duty PurpleAir alerts: https://www.watchduty.org/blog/introducing-personalized-alerts-for-wind-humidity-air-quality-aqi-and-more
- Public Lab PurpleAir thread: https://publiclab.org/n/27829
- Apple Watch heart rate: https://support.apple.com/en-gw/guide/watch/heart-rate-apda88aefe4c/6.0
- rule-engine: https://zerosteiner.github.io/rule-engine/
- business-rules: https://pypi.org/project/business-rules/
- durable_rules: https://github.com/jruizgit/rules
- JsonLogic: https://jsonlogic.com/
- cel-python: https://github.com/cloud-custodian/cel-python
- GoRules ZEN Python SDK: https://docs.gorules.io/developers/sdks/python
- Package versions and dates: PyPI JSON API (https://pypi.org/pypi/PACKAGE/json) and GitHub repo API (https://api.github.com/repos/OWNER/REPO), queried 2026-10-18
- NIST EWMA chart: https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm
- NIST CUSUM chart: https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm
- Adams & MacKay 2007, BOCPD: https://arxiv.org/abs/0710.3742
- ruptures: https://centre-borelli.github.io/ruptures-docs/
- river ADWIN: https://riverml.xyz/latest/api/drift/ADWIN/
- river HalfSpaceTrees: https://riverml.xyz/latest/api/anomaly/HalfSpaceTrees/
- changefinder: https://github.com/shunsukeaihara/changefinder
- Kats: https://github.com/facebookresearch/Kats
- Merlion (archived): https://github.com/salesforce/Merlion
