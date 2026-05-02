from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from backend.db import database as db_module
from backend.db.models import SummaryRow, fetch_summary

router = APIRouter(tags=["summary"])


def _resolve_range(
    range_key: str,
    from_date: Optional[str],
    to_date: Optional[str],
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if range_key == "today":
        return today_start.isoformat(), now.isoformat()
    elif range_key == "7d":
        return (today_start - timedelta(days=7)).isoformat(), now.isoformat()
    elif range_key == "30d":
        return (today_start - timedelta(days=30)).isoformat(), now.isoformat()
    elif range_key == "custom" and from_date and to_date:
        return from_date, to_date
    else:
        return today_start.isoformat(), now.isoformat()


def _aggregate_rows(rows: list[SummaryRow]) -> dict:
    total_input = sum(r.input_tokens for r in rows)
    total_output = sum(r.output_tokens for r in rows)
    total_cache_read = sum(r.cache_read_tokens for r in rows)
    total_cache_write = sum(r.cache_write_tokens for r in rows)
    total_cost = sum(r.cost_usd for r in rows)
    total_calls = sum(r.call_count for r in rows)

    return {
        "total_tokens": total_input + total_output + total_cache_read + total_cache_write,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "cache_tokens": total_cache_read + total_cache_write,
        "cost_usd": round(total_cost, 6),
        "call_count": total_calls,
        "breakdown": [
            {
                "agent": r.agent,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "cache_write_tokens": r.cache_write_tokens,
                "cost_usd": r.cost_usd,
                "call_count": r.call_count,
            }
            for r in rows
        ],
    }


@router.get("/summary")
async def get_summary(
    range: str = Query("today", alias="range"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    agent: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    group_by: str = Query("agent"),
):
    db = await db_module.get_db()
    from_ts, to_ts = _resolve_range(range, from_date, to_date)

    agents = agent.split(",") if agent else None
    models = model.split(",") if model else None

    rows = await fetch_summary(
        db,
        agents=agents,
        models=models,
        from_ts=from_ts,
        to_ts=to_ts,
        group_by=group_by,
    )

    return _aggregate_rows(rows)
