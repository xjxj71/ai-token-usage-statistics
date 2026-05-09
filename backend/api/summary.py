from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from backend.db import database as db_module
from backend.db.models import SummaryRow, fetch_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["summary"])

from backend.api.constants import IGNORED_MODELS


def _resolve_range(
    range_key: str,
    from_date: Optional[str],
    to_date: Optional[str],
) -> tuple[str, str]:
    # Use local timezone so "today" means local midnight, not UTC midnight.
    import zoneinfo
    try:
        local_tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    except Exception:
        local_tz = timezone(timedelta(hours=8))

    now_local = datetime.now(local_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert to UTC for DB comparison (timestamps are stored in UTC)
    today_start_utc = today_start_local.astimezone(timezone.utc)
    now_utc = now_local.astimezone(timezone.utc)

    if range_key == "today":
        return today_start_utc.isoformat(), now_utc.isoformat()
    elif range_key == "7d":
        start = today_start_utc - timedelta(days=7)
        return start.isoformat(), now_utc.isoformat()
    elif range_key == "30d":
        start = today_start_utc - timedelta(days=30)
        return start.isoformat(), now_utc.isoformat()
    elif range_key == "custom" and from_date and to_date:
        return from_date, to_date
    else:
        return today_start_utc.isoformat(), now_utc.isoformat()


def _aggregate_rows(rows: list[SummaryRow], group_by: str = "agent") -> dict:
    # 仅在按模型分组时过滤掉无意义的模型
    # 按 agent 分组时 model 字段为空字符串，不应被过滤
    if group_by == "model":
        clean_rows = [r for r in rows if r.model.lower() not in IGNORED_MODELS]
    else:
        clean_rows = rows

    # 汇总统计仍基于全部数据（包含被过滤的模型）
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
            for r in clean_rows
        ],
    }


@router.get("/summary")
async def get_summary(
    range_key: str = Query("today", alias="range"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    agent: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    group_by: str = Query("agent"),
):
    db = await db_module.get_db()
    from_ts, to_ts = _resolve_range(range_key, from_date, to_date)

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

    return _aggregate_rows(rows, group_by=group_by)
