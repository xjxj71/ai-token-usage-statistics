"""Shared date range resolution utilities for the API layer."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta, timezone

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Date format validation pattern (YYYY-MM-DD)
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_format(date_str: str, param_name: str) -> str:
    """Validate date string format (YYYY-MM-DD) and return it, or raise HTTPException."""
    if not _DATE_PATTERN.match(date_str):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name} format: '{date_str}'. Expected YYYY-MM-DD.",
        )
    return date_str


def resolve_range(
    range_key: str,
    from_date: str | None,
    to_date: str | None,
    tz_name: str = "Asia/Shanghai",
) -> tuple[str, str]:
    """Resolve a range key to (from_ts, to_ts) UTC ISO strings ending in Z.

    Supports: 'today', '7d', '30d', 'custom' (requires from_date + to_date,
    both inclusive). Unrecognized keys or invalid dates raise HTTP 400.
    """
    import zoneinfo
    try:
        local_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to load timezone %s, falling back to UTC+8", tz_name)
        local_tz = timezone(timedelta(hours=8))

    now_local = datetime.now(local_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert to UTC for DB comparison (timestamps are stored in UTC with Z suffix)
    today_start_utc = today_start_local.astimezone(UTC)
    now_utc = now_local.astimezone(UTC)

    if range_key == "today":
        return _fmt_z(today_start_utc), _fmt_z(now_utc)
    elif range_key == "7d":
        start = today_start_utc - timedelta(days=7)
        return _fmt_z(start), _fmt_z(now_utc)
    elif range_key == "30d":
        start = today_start_utc - timedelta(days=30)
        return _fmt_z(start), _fmt_z(now_utc)
    elif range_key == "custom" and from_date and to_date:
        _validate_date_format(from_date, "from")
        _validate_date_format(to_date, "to")

        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=local_tz)
        to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=local_tz)

        if from_dt > to_dt:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid range: from ({from_date}) is after to ({to_date}).",
            )

        # Full local days, converted to UTC — the `to` day is inclusive
        # (boundary is the following local midnight, exclusive).
        return _fmt_z(from_dt.astimezone(UTC)), _fmt_z((to_dt + timedelta(days=1)).astimezone(UTC))
    elif range_key == "custom":
        raise HTTPException(
            status_code=400,
            detail="Custom range requires both 'from' and 'to' (YYYY-MM-DD).",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range: '{range_key}'. Expected today / 7d / 30d / custom.",
        )


def _fmt_z(dt: datetime) -> str:
    """Format a UTC datetime as an ISO string ending in ``Z`` (e.g. ``2026-05-25T16:00:00Z``).

    Strips microseconds and timezone offset, appending ``Z`` — matching the
    format used in the database for reliable string comparison.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_z(ts: str) -> datetime:
    """Parse a Z-suffixed UTC ISO string (inverse of ``_fmt_z``)."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def previous_window(from_ts: str, to_ts: str) -> tuple[str, str]:
    """Return the equal-length window immediately before ``[from_ts, to_ts)``.

    Used for period-over-period comparison: "today so far" compares against
    yesterday up to the same time of day, "7d" against the prior 7 days, and
    custom ranges against an equal-length window right before them.
    """
    from_dt = _parse_z(from_ts)
    to_dt = _parse_z(to_ts)
    duration = to_dt - from_dt
    return _fmt_z(from_dt - duration), _fmt_z(from_dt)
