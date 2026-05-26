from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query

from backend.api.constants import IGNORED_MODELS
from backend.api.range_utils import resolve_range
from backend.db import database as db_module
from backend.db.models import SummaryRow, fetch_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["summary"])


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
    group_by: str = Query("agent", pattern="^(agent|model)$"),
):
    db = await db_module.get_db()
    from_ts, to_ts = resolve_range(range_key, from_date, to_date)

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
