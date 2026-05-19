"""Application timezone helpers (default: Vietnam UTC+7)."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional, Union

DatetimeLike = Union[datetime, date, time]

APP_TIMEZONE_NAME = (os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh").strip()


def _load_app_timezone():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(APP_TIMEZONE_NAME)
    except Exception:
        # Windows dev boxes without tzdata still get stable UTC+7.
        return timezone(timedelta(hours=7), name="UTC+07")


APP_TIMEZONE = _load_app_timezone()


def now_app() -> datetime:
    """Timezone-aware 'now' in the application timezone (+07:00 for VN)."""
    return datetime.now(APP_TIMEZONE)


def to_api_timestamp(value: Optional[DatetimeLike]) -> Optional[str]:
    """Serialize datetimes for API JSON with explicit offset (e.g. +07:00)."""
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=APP_TIMEZONE)
    elif isinstance(value, time):
        today = now_app().date()
        dt = datetime.combine(today, value, tzinfo=APP_TIMEZONE)
    else:
        return str(value)

    if dt.tzinfo is None:
        # Legacy rows: written via datetime.utcnow() before timezone fix.
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(APP_TIMEZONE).isoformat(timespec="seconds")
