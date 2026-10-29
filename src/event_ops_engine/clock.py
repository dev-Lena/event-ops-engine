"""Layer: lib. The only module that turns dates and datetimes into engine numbers.

Domain boundary rules (docs/glossary.md): a date is Asia/Seoul midnight; the engine
sees UTC epoch seconds; "days left" is counted in whole days between calendar dates.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

EVENT_TIME_ZONE = ZoneInfo("Asia/Seoul")
WEEK_SECONDS = 7 * 24 * 60 * 60
"""Same value as the literal 604800 in rules/promotion.dl."""


def to_epoch(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ValueError("datetime must carry a time zone")
    return int(moment.timestamp())


def session_start(session_date: date) -> datetime:
    return datetime.combine(session_date, time.min, tzinfo=EVENT_TIME_ZONE)


def days_left(now: datetime, session_date: date) -> int:
    """Whole calendar days from `now` (in event time zone) to the session date; negative if past."""
    today = now.astimezone(EVENT_TIME_ZONE).date()
    return (session_date - today).days
