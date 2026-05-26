"""Tests for backend.api.range_utils."""

from datetime import datetime, timezone

import pytest

from backend.api.range_utils import resolve_range


@pytest.mark.unit
class TestResolveRange:
    def test_today_returns_same_day_range(self):
        from_ts, to_ts = resolve_range("today", None, None)
        assert from_ts is not None
        assert to_ts is not None
        assert from_ts < to_ts

    def test_7d_returns_week_range(self):
        from_ts, to_ts = resolve_range("7d", None, None)
        from_dt = datetime.fromisoformat(from_ts)
        to_dt = datetime.fromisoformat(to_ts)
        delta = to_dt - from_dt
        assert 6 <= delta.days <= 8  # ~7 days

    def test_30d_returns_month_range(self):
        from_ts, to_ts = resolve_range("30d", None, None)
        from_dt = datetime.fromisoformat(from_ts)
        to_dt = datetime.fromisoformat(to_ts)
        delta = to_dt - from_dt
        assert 29 <= delta.days <= 31  # ~30 days

    def test_custom_returns_provided_dates(self):
        from_ts, to_ts = resolve_range("custom", "2026-01-01", "2026-12-31")
        assert from_ts == "2026-01-01"
        assert to_ts == "2026-12-31"

    def test_custom_without_dates_falls_back_to_today(self):
        from_ts, to_ts = resolve_range("custom", None, None)
        assert from_ts is not None
        assert to_ts is not None

    def test_unknown_key_falls_back_to_today(self):
        from_ts, to_ts = resolve_range("invalid_key", None, None)
        today_from, today_to = resolve_range("today", None, None)
        # Both should be same-day range (from may differ slightly due to now() calls)
        assert from_ts[:10] == today_from[:10]  # same date prefix
        assert to_ts[:10] == today_to[:10]

    def test_timezone_handling(self):
        from_ts, to_ts = resolve_range("today", None, None, tz_name="Asia/Shanghai")
        assert from_ts is not None
        assert to_ts is not None

    def test_invalid_timezone_falls_back(self):
        from_ts, to_ts = resolve_range("today", None, None, tz_name="Invalid/Zone")
        assert from_ts is not None
        assert to_ts is not None
