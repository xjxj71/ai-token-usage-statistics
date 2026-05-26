"""API endpoint for daily token usage trend data (line charts)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from backend.api.range_utils import resolve_range
from backend.db import database as db_module
from backend.db.models import fetch_trend

router = APIRouter(tags=["trend"])


def _generate_slots(from_ts: str, to_ts: str, granularity: str) -> list[str]:
    """Generate a complete list of time slots between ``from_ts`` and ``to_ts``
    in **Shanghai timezone** (UTC+8).

    Hourly: every hour from the start-of-hour to the start-of-hour.
    Daily:  every date (``YYYY-MM-DD``) from start to end.
    """
    slots: list[str] = []
    SHANGHAI = timezone(timedelta(hours=8))

    def _parse_iso(ts: str) -> datetime:
        """Parse ISO string, handling both full and date-only formats."""
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            pass
        try:
            return datetime.strptime(ts, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
        return datetime.now(timezone.utc)

    start = _parse_iso(from_ts).astimezone(SHANGHAI)
    end = _parse_iso(to_ts).astimezone(SHANGHAI)

    if granularity == "hour":
        start = start.replace(minute=0, second=0, microsecond=0)
        end = end.replace(minute=0, second=0, microsecond=0)
        cursor = start
        while cursor <= end:
            slots.append(cursor.strftime("%Y-%m-%dT%H"))
            cursor += timedelta(hours=1)
    else:
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        cursor = start
        while cursor <= end:
            slots.append(cursor.strftime("%Y-%m-%d"))
            cursor += timedelta(days=1)

    return slots


def _pivot(rows: list[dict], granularity: str, from_ts: str, to_ts: str) -> dict:
    """Convert flat DB rows into ECharts-friendly wide format.

    Generates the *full* list of time slots (hours or days) and fills
    missing slots with zero, so the line chart shows a continuous axis.

    Input:  [{date: "2026-05-20", name: "hermes", total_tokens: 50000}, ...]
    Output: {
      dates: ["2026-05-20", "2026-05-21", ...],
      series: [{name: "hermes", data: [50000, 0, ...]}, ...]
    }
    """
    # Generate complete time slots
    dates = _generate_slots(from_ts, to_ts, granularity)

    # Collect all names and data
    names_set: set[str] = set()
    by_date_name: dict[tuple[str, str], int] = {}
    for r in rows:
        names_set.add(r["name"])
        by_date_name[(r["date"], r["name"])] = r["total_tokens"]

    names = sorted(names_set)

    # Totals across all names per date
    totals_by_date: dict[str, int] = {}
    for r in rows:
        totals_by_date[r["date"]] = totals_by_date.get(r["date"], 0) + r["total_tokens"]

    series = [
        {
            "name": "总计",
            "data": [totals_by_date.get(d, 0) for d in dates],
        },
        *[
            {
                "name": name,
                "data": [by_date_name.get((d, name), 0) for d in dates],
            }
            for name in names
        ],
    ]

    return {
        "dates": dates,
        "series": series,
    }


@router.get("/trend")
async def get_trend(
    range_key: str = Query("30d", alias="range"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    agent: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    group_by: str = Query("agent", pattern="^(agent|model)$"),
    granularity: str = Query("day", pattern="^(day|hour)$"),
):
    db = await db_module.get_db()
    from_ts, to_ts = resolve_range(range_key, from_date, to_date)

    agents = agent.split(",") if agent else None
    models = model.split(",") if model else None

    rows = await fetch_trend(
        db,
        group_by=group_by,
        granularity=granularity,
        from_ts=from_ts,
        to_ts=to_ts,
        agents=agents,
        models=models,
    )

    return _pivot(rows, granularity=granularity, from_ts=from_ts, to_ts=to_ts)