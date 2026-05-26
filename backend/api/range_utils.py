"""Shared date range resolution utilities for the API layer."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_range(
    range_key: str,
    from_date: Optional[str],
    to_date: Optional[str],
    tz_name: str = "Asia/Shanghai",
) -> tuple[str, str]:
    """Resolve a range key to (from_ts, to_ts) ISO strings.

    Supports: 'today', '7d', '30d', 'custom' (requires from_date + to_date).
    Falls back to today if key is unrecognized.
    """
    import zoneinfo
    try:
        local_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        logger.debug("Failed to load timezone %s, falling back to UTC+8", tz_name)
        local_tz = timezone(timedelta(hours=8))

    now_local = datetime.now(local_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert to UTC for DB comparison (timestamps are stored in UTC with Z suffix)
    today_start_utc = today_start_local.astimezone(timezone.utc)
    now_utc = now_local.astimezone(timezone.utc)

    if range_key == "today":
        return _fmt_z(today_start_utc), _fmt_z(now_utc)
    elif range_key == "7d":
        start = today_start_utc - timedelta(days=7)
        return _fmt_z(start), _fmt_z(now_utc)
    elif range_key == "30d":
        start = today_start_utc - timedelta(days=30)
        return _fmt_z(start), _fmt_z(now_utc)
    elif range_key == "custom" and from_date and to_date:
        return from_date, to_date
    else:
        return _fmt_z(today_start_utc), _fmt_z(now_utc)


def _fmt_z(dt: datetime) -> str:
    """Format a UTC datetime as an ISO string ending in ``Z`` (e.g. ``2026-05-25T16:00:00Z``).

    Strips microseconds and timezone offset, appending ``Z`` — matching the
    format used in the database for reliable string comparison.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
