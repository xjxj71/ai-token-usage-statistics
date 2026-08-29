"""Tests for backend.api.range_utils."""

from datetime import datetime

import pytest
from fastapi import HTTPException

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

    def test_custom_returns_full_day_utc_boundaries(self):
        from_ts, to_ts = resolve_range("custom", "2026-01-01", "2026-01-03")
        # Asia/Shanghai is UTC+8: local midnight 2026-01-01 = 2025-12-31T16:00Z
        assert from_ts == "2025-12-31T16:00:00Z"
        # `to` day is inclusive: boundary is local midnight of the next day
        assert to_ts == "2026-01-03T16:00:00Z"

    def test_custom_same_day_spans_one_full_day(self):
        from_ts, to_ts = resolve_range("custom", "2026-06-11", "2026-06-11")
        from_dt = datetime.fromisoformat(from_ts)
        to_dt = datetime.fromisoformat(to_ts)
        assert (to_dt - from_dt).days == 1

    def test_custom_without_dates_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            resolve_range("custom", None, None)
        assert exc_info.value.status_code == 400

    def test_unknown_key_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            resolve_range("invalid_key", None, None)
        assert exc_info.value.status_code == 400

    def test_custom_from_after_to_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            resolve_range("custom", "2026-06-11", "2026-06-01")
        assert exc_info.value.status_code == 400

    def test_custom_invalid_date_format_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            resolve_range("custom", "2026/06/01", "2026-06-11")
        assert exc_info.value.status_code == 400

    def test_timezone_handling(self):
        from_ts, to_ts = resolve_range("today", None, None, tz_name="Asia/Shanghai")
        assert from_ts is not None
        assert to_ts is not None

    def test_invalid_timezone_falls_back(self):
        from_ts, to_ts = resolve_range("today", None, None, tz_name="Invalid/Zone")
        assert from_ts is not None
        assert to_ts is not None
