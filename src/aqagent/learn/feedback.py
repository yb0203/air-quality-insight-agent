"""L1: record what a user did with a notice. Recording only; nothing here changes user_rules."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aqagent.db import feedback, notifications

Action = Literal["acted", "dismissed", "not_useful"]
ACTIONS: tuple[str, ...] = get_args(Action)


class UnknownNotification(LookupError):
    """No notification with the given id (for this user)."""


def record(conn: Connection, notification_id: int, user_id: str, action: Action, at: datetime) -> int:
    """Insert a feedback row for `notification_id`; returns its id. The caller owns the transaction."""
    if action not in ACTIONS:
        raise ValueError(f"unknown feedback action {action!r}; expected one of {ACTIONS}")
    owner = conn.execute(sa.select(notifications.c.user_id)
                         .where(notifications.c.id == notification_id)).scalar()
    if owner is None or owner != user_id:
        raise UnknownNotification(f"no notification {notification_id} for user {user_id!r}")
    res = conn.execute(feedback.insert().values(notification_id=notification_id, user_id=user_id,
                                                action=action, at=at))
    return res.inserted_primary_key[0]
