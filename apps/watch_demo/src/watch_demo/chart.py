"""Geometry for the server-rendered SVG chart beside the watch.

One measure (PM2.5) on one axis, the station's usual level for each hour as a
reference line, EPA bands as faint washes behind, and a lane underneath with
one mark per decision the agent took. Every hour is a link that moves the
watch to that moment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Decision, Reading
from .why import clock

WIDTH, HEIGHT = 600, 318
LEFT, RIGHT, TOP, BOTTOM = 44, 548, 14, 226
LANE_Y = 276
GAP = timedelta(hours=3)  # a longer gap between readings breaks the line

BANDS = [
    ("good", "Good", 0.0, 9.0),
    ("moderate", "Moderate", 9.0, 35.4),
    ("usg", "USG", 35.4, 55.4),
    ("unhealthy", "Unhealthy", 55.4, 125.4),
    ("very_unhealthy", "Very unhealthy", 125.4, 225.4),
    ("hazardous", "Hazardous", 225.4, float("inf")),
]

OUTCOME_LABELS = {"sent": "Sent", "held": "Held", "suppressed": "Stayed quiet", "no_event": "Nothing to say"}


@dataclass
class Chart:
    width: int = WIDTH
    height: int = HEIGHT
    left: int = LEFT
    right: int = RIGHT
    top: int = TOP
    bottom: int = BOTTOM
    lane_y: int = LANE_Y
    zones: list[dict] = field(default_factory=list)
    yticks: list[dict] = field(default_factory=list)
    xticks: list[dict] = field(default_factory=list)
    line: str = ""
    usual: str = ""
    end_label: dict | None = None
    usual_label: dict | None = None
    ignored: list[dict] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)
    marks: list[dict] = field(default_factory=list)
    cursor_x: float = RIGHT
    title: str = ""


def _nice_max(v: float) -> tuple[float, float]:
    """A clean axis top and tick step for values up to v."""
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500):
        top = step * -(-v // step)
        if top / step <= 5:
            return top, step
    return 1000 * -(-v // 1000), 1000


def _path(points: list[tuple[datetime, float]], x, y) -> str:
    out, prev = [], None
    for t, v in points:
        cmd = "M" if prev is None or t - prev > GAP else "L"
        out.append(f"{cmd}{x(t):.1f},{y(v):.1f}")
        prev = t
    return " ".join(out)


def build_chart(
    readings: list[Reading],
    decisions: list[Decision],
    start: datetime,
    end: datetime,
    cursor: datetime,
    tz: ZoneInfo,
    href,
    city: str,
    focus: datetime | None = None,
) -> Chart:
    span = (end - start).total_seconds()

    def x(t: datetime) -> float:
        return LEFT + (t - start).total_seconds() / span * (RIGHT - LEFT)

    clean = [r for r in readings if r.pm25 is not None and not r.dq]
    peak = max([r.pm25 for r in clean] + [r.typical_pm25 or 0 for r in readings] + [5.0])
    ymax, step = _nice_max(peak * 1.12)

    def y(v: float) -> float:
        return BOTTOM - min(v, ymax) / ymax * (BOTTOM - TOP)

    c = Chart(cursor_x=x(min(max(cursor, start), end)))
    local_start, local_end = start.astimezone(tz), end.astimezone(tz)
    c.title = f"{city} · PM2.5 µg/m³ · {local_start:%a} {local_start.day} {local_start:%b} {local_start:%H:%M} to {local_end:%a} {local_end:%H:%M}"

    for key, label, lo, hi in BANDS:
        if lo >= ymax:
            break
        top, bottom = y(min(hi, ymax)), y(lo)
        c.zones.append({"band": key, "label": label, "y": top, "h": bottom - top, "show_label": bottom - top >= 16})

    c.yticks = [{"y": y(v), "label": f"{v:g}"} for v in range(0, int(ymax) + 1, int(step))]

    first_tick = local_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while first_tick.hour % 3:
        first_tick += timedelta(hours=1)
    t = first_tick
    while t <= local_end:
        c.xticks.append({"x": x(t), "label": clock(t, tz)})
        t += timedelta(hours=3)

    c.line = _path([(r.at, r.pm25) for r in clean], x, y)
    usual = [(r.at, r.typical_pm25) for r in readings if r.typical_pm25 is not None]
    c.usual = _path(usual, x, y)
    if clean:
        last = clean[-1]
        c.end_label = {"x": x(last.at), "y": y(last.pm25), "label": f"{last.pm25:.0f}"}
    if usual:
        c.usual_label = {"x": x(usual[-1][0]), "y": y(usual[-1][1])}

    for r in readings:
        if r.dq and r.pm25 is not None:
            gx = x(r.at)
            c.ignored.append({
                "x": gx,
                "y": y(r.pm25) if r.pm25 <= ymax else TOP + 6,
                "label": f"{r.pm25:.0f} ignored",
                "code": r.dq,
                "flip": gx > RIGHT - 90,  # label to the left near the right edge
            })

    by_time: dict[datetime, list[Decision]] = {}
    for d in decisions:
        by_time.setdefault(d.evaluated_at, []).append(d)

    # Hit targets: one column per reading, wider than any mark.
    xs = [x(r.at) for r in readings]
    for i, r in enumerate(readings):
        left = (xs[i - 1] + xs[i]) / 2 if i else LEFT
        right = (xs[i] + xs[i + 1]) / 2 if i + 1 < len(xs) else RIGHT
        tip = [f"{clock(r.at, tz)}", f"PM2.5 {r.pm25:.0f}" if r.pm25 is not None else "no reading"]
        if r.typical_pm25 is not None:
            tip.append(f"usual {r.typical_pm25:.0f}")
        if r.dq:
            tip.append(f"excluded ({r.dq})")
        for d in by_time.get(r.at, []):
            tip.append(f"{OUTCOME_LABELS[d.outcome].lower()}: {d.reason_code}")
        c.columns.append({"x": left, "w": right - left, "href": href(r.at), "tip": " · ".join(tip)})

    for d in decisions:
        if not start <= d.evaluated_at <= end:
            continue
        mark = {
            "x": x(d.evaluated_at),
            "kind": d.outcome,
            "href": href(d.evaluated_at),
            "tip": f"{clock(d.evaluated_at, tz)} · {OUTCOME_LABELS[d.outcome]} · {d.reason_code}",
            "label": None,
            "focus": focus is not None and d.evaluated_at == focus and d.outcome == "sent",
        }
        if d.outcome == "sent":
            mark["label"] = clock(d.evaluated_at, tz)
        elif d.outcome == "held":
            mark["label"] = "held"
        elif d.reason_code.startswith("DQ_"):
            mark["kind"] = "ignored"
        c.marks.append(mark)
    # Loud marks last so they sit on top.
    order = {"no_event": 0, "suppressed": 1, "ignored": 2, "held": 3, "sent": 4}
    c.marks.sort(key=lambda m: order[m["kind"]])
    return c
