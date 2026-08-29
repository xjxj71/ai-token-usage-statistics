"""Tests for backend.api.range_utils."""

from datetime import datetime

import pytest
from fastapi import HTTPException

from backend.api.range_utils import previous_window, resolve_range


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


@pytest.mark.unit
class TestPreviousWindow:
    def test_single_day_shifts_back_one_day(self):
        prev_from, prev_to = previous_window("2026-05-02T16:00:00Z", "2026-05-03T16:00:00Z")
        assert prev_from == "2026-05-01T16:00:00Z"
        assert prev_to == "2026-05-02T16:00:00Z"

    def test_partial_day_compares_same_time_of_day(self):
        # "today 00:00 → 08:00 Shanghai" (16:00Z → 00:00Z next day) must map to
        # "yesterday 00:00 → 08:00 Shanghai" = 08:00Z → 16:00Z on the same UTC day
        prev_from, prev_to = previous_window("2026-05-02T16:00:00Z", "2026-05-03T00:00:00Z")
        assert prev_from == "2026-05-02T08:00:00Z"
        assert prev_to == "2026-05-02T16:00:00Z"

    def test_cross_month_boundary(self):
        prev_from, prev_to = previous_window("2026-03-01T16:00:00Z", "2026-03-03T16:00:00Z")
        assert prev_from == "2026-02-27T16:00:00Z"
        assert prev_to == "2026-03-01T16:00:00Z"

    def test_window_length_is_preserved(self):
        from_ts, to_ts = "2026-05-02T16:00:00Z", "2026-05-09T16:00:00Z"
        prev_from, prev_to = previous_window(from_ts, to_ts)
        assert datetime.fromisoformat(prev_to) - datetime.fromisoformat(prev_from) == (
            datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)
        )
