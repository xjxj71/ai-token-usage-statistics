from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query

from backend.api.constants import IGNORED_MODELS
from backend.api.range_utils import resolve_range
from backend.db import database as db_module
from backend.db.models import fetch_cache_ratio

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cache-ratio"])


@router.get("/cache-ratio")
async def get_cache_ratio(
    range_key: str = Query("today", alias="range"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    agent: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    view: str = Query("by_agent", pattern="^(by_agent|by_model|by_agent_model)$"),
):
    """缓存命中率统计接口。

    - view=by_agent: 按 Agent 分组，每个 Agent 的整体缓存率
    - view=by_model: 按模型分组，每个模型在所有 Agent 中的缓存率
    - view=by_agent_model: 按 Agent × 模型交叉分组
    """
    db = await db_module.get_db()
    from_ts, to_ts = resolve_range(range_key, from_date, to_date)

    agents = agent.split(",") if agent else None
    models = model.split(",") if model else None

    group_map = {
        "by_agent": "agent",
        "by_model": "model",
        "by_agent_model": "agent_model",
    }

    rows = await fetch_cache_ratio(
        db,
        agents=agents,
        models=models,
        from_ts=from_ts,
        to_ts=to_ts,
        group_by=group_map[view],
    )

    # 过滤掉无意义模型（仅在有 model 字段时）
    filtered = []
    for r in rows:
        if r.model and r.model.lower() in IGNORED_MODELS:
            continue
        filtered.append({
            "agent": r.agent,
            "model": r.model,
            "total_tokens": r.total_tokens,
            "cache_read_tokens": r.cache_read_tokens,
            "cache_ratio": r.cache_ratio,
        })

    # 计算整体缓存率
    total_tokens = sum(r.total_tokens for r in rows)
    total_cache_read = sum(r.cache_read_tokens for r in rows)
    overall_ratio = round(total_cache_read / total_tokens, 4) if total_tokens > 0 else 0.0

    return {
        "overall_cache_ratio": overall_ratio,
        "items": filtered,
    }
