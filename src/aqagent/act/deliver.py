"""A2 DELIVER (stub): in the demo, a notice is delivered when it lands in the person's feed."""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from aqagent import db
from aqagent.act.compose import ComposedMessage


def deliver(conn: sa.Connection, *, decision_id: int, user_id: str, msg: ComposedMessage, insight: dict,
            kind: str, at: datetime) -> int:
    res = conn.execute(db.notifications.insert().values(
        decision_id=decision_id, user_id=user_id, created_at=at, deliver_after=at, delivered_at=at,
        kind=kind, body=msg.body, next_action=msg.next_action, context_facts=insight, generator=msg.generator))
    return res.inserted_primary_key[0]
