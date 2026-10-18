"""S3 RESOLVE (stub): which station a user's rules point at. v1 has exactly one station per user."""
from __future__ import annotations

from aqagent.decide.rules import Rules


def station_for(rules: Rules) -> int:
    return rules.location.station_id
