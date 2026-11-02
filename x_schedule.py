"""Shared São Paulo schedule for fifteen X posts per day."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("America/Sao_Paulo")
POST_HOURS = tuple(range(8, 23))


def slots(day: date) -> list[datetime]:
    return [datetime.combine(day, time(hour), TIMEZONE) for hour in POST_HOURS]
