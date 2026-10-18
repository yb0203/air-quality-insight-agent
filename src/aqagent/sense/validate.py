"""S2 VALIDATE: per-hour data-quality checks (S-C §2). Pure functions, no I/O."""
from __future__ import annotations

from datetime import datetime, timedelta

from aqagent import params
from aqagent.types import CheckedReading, Reading, ReasonCode

HOUR = timedelta(hours=1)


def _dedupe_sorted(readings: list[Reading]) -> list[Reading]:
    """Ascending by period_end; for a repeated period_end the last one given wins (newest revision)."""
    by_end: dict[datetime, Reading] = {}
    for r in readings:
        by_end[r.period_end] = r
    return [by_end[k] for k in sorted(by_end)]


def _is_invalid(r: Reading) -> bool:
    return r.value is None or r.value < 0 or r.value > params.INVALID_MAX


def _stuck_indices(rs: list[Reading], invalid: list[bool]) -> set[int]:
    """Indices inside runs of >= STUCK_HOURS identical values on consecutive hours."""
    out: set[int] = set()
    start = 0
    for i in range(1, len(rs) + 1):
        same = (
            i < len(rs)
            and not invalid[i]
            and not invalid[i - 1]
            and rs[i].value == rs[i - 1].value
            and rs[i].period_end - rs[i - 1].period_end == HOUR
        )
        if not same:
            if i - start >= params.STUCK_HOURS:
                out.update(range(start, i))
            start = i
    return out


def _is_glitch(v: float, prev: float, nxt: float) -> bool:
    return (
        v > params.GLITCH_RATIO * max(prev, 1)
        and v > params.GLITCH_RATIO * max(nxt, 1)
        and v - prev > params.GLITCH_DELTA
    )


def validate(readings: list[Reading], provisional_last: bool = True) -> list[CheckedReading]:
    """Label every reading with why it is excluded from scoring (None = usable), ascending by time.

    Precedence when several checks fail: DQ_INVALID, DQ_LOW_COVERAGE, DQ_STUCK, DQ_SUSPECT.
    The glitch check compares with the nearest valid neighbours. The newest reading has no t+1,
    so with `provisional_last` it is marked provisional (clean for now, re-checked next run).
    """
    rs = _dedupe_sorted(readings)
    invalid = [_is_invalid(r) for r in rs]
    stuck = _stuck_indices(rs, invalid)
    valid_idx = [i for i, bad in enumerate(invalid) if not bad]
    neighbours = {
        i: (valid_idx[k - 1] if k > 0 else None, valid_idx[k + 1] if k + 1 < len(valid_idx) else None)
        for k, i in enumerate(valid_idx)
    }
    out: list[CheckedReading] = []
    for i, r in enumerate(rs):
        code: ReasonCode | None = None
        provisional = False
        if invalid[i]:
            code = ReasonCode.DQ_INVALID
        elif r.coverage_pct is not None and r.coverage_pct < params.LOW_COVERAGE_PCT:
            code = ReasonCode.DQ_LOW_COVERAGE
        elif i in stuck:
            code = ReasonCode.DQ_STUCK
        else:
            prev, nxt = neighbours[i]
            if prev is not None and nxt is not None:
                if _is_glitch(r.value, rs[prev].value, rs[nxt].value):
                    code = ReasonCode.DQ_SUSPECT
            elif nxt is None and i == len(rs) - 1 and provisional_last:
                provisional = True
        out.append(CheckedReading(r, code, provisional))
    return out


def gap_breaks(readings: list[Reading]) -> set[datetime]:
    """period_ends that follow more than GAP_RESET_HOURS missing hours since the previous reading."""
    ends = sorted({r.period_end for r in readings})
    limit = timedelta(hours=params.GAP_RESET_HOURS)
    return {b for a, b in zip(ends, ends[1:]) if b - a - HOUR > limit}
