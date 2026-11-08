"""Time boundary rules: Seoul calendar days, epoch seconds, time zone required."""

from datetime import date, datetime, time, timezone

import pytest

from event_ops_engine.clock import (
    WEEK_SECONDS,
    days_left,
    earliest_promotion_cutoff,
    promotion_cutoff,
    session_start,
    to_epoch,
)


def test_days_left_counts_calendar_days_in_seoul() -> None:
    now = datetime.fromisoformat("2026-11-07T10:00:00+09:00")
    assert days_left(now, date(2026, 11, 14)) == 7
    assert days_left(now, date(2026, 11, 7)) == 0
    assert days_left(now, date(2026, 11, 6)) == -1


def test_days_left_converts_utc_now_to_seoul_date() -> None:
    # 2026-11-07 16:30 UTC is already 2026-11-08 01:30 in Seoul.
    now = datetime(2026, 11, 7, 16, 30, tzinfo=timezone.utc)
    assert days_left(now, date(2026, 11, 8)) == 0


def test_to_epoch_requires_time_zone() -> None:
    with pytest.raises(ValueError):
        to_epoch(datetime(2026, 11, 7, 10, 0))


def test_session_start_is_seoul_midnight() -> None:
    assert to_epoch(session_start(date(2026, 11, 14))) == to_epoch(
        datetime.fromisoformat("2026-11-14T00:00:00+09:00")
    )


def test_week_constant_matches_rule_literal() -> None:
    rules = open("rules/promotion.dl", encoding="utf-8").read()
    assert f"T + {WEEK_SECONDS} > N" in rules


def test_promotion_cutoff_counts_back_from_the_seoul_start_time() -> None:
    cutoff = promotion_cutoff(date(2026, 11, 10), time(1, 0), 2)
    assert cutoff.isoformat() == "2026-11-09T23:00:00+09:00"  # crosses midnight
    earliest = earliest_promotion_cutoff(date(2026, 11, 10), 2)
    assert earliest.isoformat() == "2026-11-09T22:00:00+09:00"
