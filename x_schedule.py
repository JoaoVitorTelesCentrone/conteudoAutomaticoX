"""Shared São Paulo schedule: thirty X posts per day, every 30 minutes."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("America/Sao_Paulo")
# 08:00, 08:30, ..., 22:30 — matches the publish cron at :17 and :47.
POST_TIMES = tuple(time(hour, minute) for hour in range(8, 23) for minute in (0, 30))


def slots(day: date) -> list[datetime]:
    return [datetime.combine(day, slot, TIMEZONE) for slot in POST_TIMES]
