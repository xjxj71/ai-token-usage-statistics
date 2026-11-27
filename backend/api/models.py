from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.constants import IGNORED_MODELS, SUPPORTED_AGENTS
from backend.api.deps import require_local_or_key
from backend.db import database as db_module
from backend.db.models import (
    fetch_distinct_agents,
    fetch_distinct_models,
    fetch_distinct_projects,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


@router.get("/models")
async def get_models():
    """返回实际使用过的模型列表（仅 token_usage 中出现且有定价信息的模型）。

    过滤掉脏数据（model='0'、'unknown'）等无意义模型。
    只返回在 model_pricing 表中存在的模型，确保下拉菜单只展示已知模型。
    """
    db = await db_module.get_db()
    used_models = await fetch_distinct_models(db)

    # 单次查询获取所有已知模型的完整定价信息
    price_rows = await db.execute_fetchall("SELECT * FROM model_pricing ORDER BY model")
    pricing = {
        r["model"]: {
            "model": r["model"],
            "input_price": r["input_price"],
            "output_price": r["output_price"],
            "cache_read_price": r["cache_read_price"],
            "cache_write_price": r["cache_write_price"],
        }
        for r in price_rows
    }

    # 只返回：在 token_usage 中出现过 + 在 model_pricing 中存在 + 不在黑名单中
    result = [
        pricing[m]
        for m in used_models
        if m.lower() not in IGNORED_MODELS and m in pricing
    ]
    return result


@router.get("/pricing")
async def get_pricing():
    db = await db_module.get_db()
    rows = await db.execute_fetchall("SELECT * FROM model_pricing ORDER BY model")
    return [
        {
            "model": r["model"],
            "input_price": r["input_price"],
            "output_price": r["output_price"],
            "cache_read_price": r["cache_read_price"],
            "cache_write_price": r["cache_write_price"],
        }
        for r in rows
    ]


@router.get("/agents")
async def get_agents():
    db = await db_module.get_db()
    agents = await fetch_distinct_agents(db)
    # 只返回白名单中支持的 agent
    return [a for a in agents if a in SUPPORTED_AGENTS]


@router.get("/projects")
async def get_projects():
    """返回出现过的项目名（来自会话工作目录，仅部分 Agent 提供该数据）。"""
    db = await db_module.get_db()
    return await fetch_distinct_projects(db)


@router.get("/config")
async def get_config():
    """返回前端需要的配置信息（汇率等）。"""
    from backend.exchange_rate import get_rate

    info = await get_rate()
    return {
        "usd_to_cny_rate": info.rate,
        "rate_source": info.source,
        "rate_updated_at": info.fetched_at or None,
    }


@router.post("/config/exchange-rate/refresh")
async def refresh_exchange_rate(request: Request):
    """强制刷新 USD→CNY 汇率（仅本机或携带有效 API Key）。"""
    from backend.exchange_rate import get_rate

    require_local_or_key(request)
    info = await get_rate(force=True)
    return {
        "usd_to_cny_rate": info.rate,
        "rate_source": info.source,
        "rate_updated_at": info.fetched_at or None,
    }


class PricingUpdate(BaseModel):
    input_price: float = Field(ge=0)
    output_price: float = Field(ge=0)
    cache_read_price: float = Field(default=0.0, ge=0)
    cache_write_price: float = Field(default=0.0, ge=0)


@router.put("/pricing/{model:path}")
async def update_pricing(model: str, body: PricingUpdate, request: Request):
    """更新指定模型的自定义定价（仅本机或携带有效 API Key）。"""
    require_local_or_key(request)
    db = await db_module.get_db()

    # 检查模型是否存在
    row = await db.execute_fetchall(
        "SELECT model FROM model_pricing WHERE model = ?", (model,)
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"模型 '{model}' 不存在")

    now = datetime.now(UTC).isoformat()
    await db.execute(
        """UPDATE model_pricing
           SET input_price = ?, output_price = ?,
               cache_read_price = ?, cache_write_price = ?, updated_at = ?,
               price_source = 'manual'
           WHERE model = ?""",
        (body.input_price, body.output_price,
         body.cache_read_price, body.cache_write_price, now, model),
    )
    await db.commit()
    # The table is what calculate_cost() bills with — apply the edit right away.
    await db_module.sync_pricing_from_db(db)

    return {
        "model": model,
        "input_price": body.input_price,
        "output_price": body.output_price,
        "cache_read_price": body.cache_read_price,
        "cache_write_price": body.cache_write_price,
        "updated_at": now,
    }


@router.get("/pricing/status")
async def pricing_status():
    """定价刷新状态：上次自动/手动时间、今日是否还会自动更新。"""
    from backend.pricing.refresh import get_status

    return get_status()


@router.post("/pricing/refresh")
async def refresh_pricing(request: Request):
    """从 OpenRouter API 一键获取最新模型定价（仅本机或携带有效 API Key）。

    手动刷新会记录时间：当天不再触发每日自动刷新。
    匹配范围含使用过但尚未定价的模型；刚拿到价格的模型会补齐其历史 0 成本记录，
    已有非零成本保持不变。
    """
    require_local_or_key(request)
    import urllib.error

    from backend.pricing.refresh import get_status, refresh_pricing_core

    try:
        result = await refresh_pricing_core(manual=True)
    except urllib.error.URLError as e:
        logger.error("OpenRouter API 请求失败: %s", e)
        raise HTTPException(status_code=502, detail=f"OpenRouter API 请求失败: {e!s}")
    except Exception:
        logger.exception("刷新定价失败")
        raise HTTPException(status_code=500, detail="刷新定价失败")

    return {**result, "total": result["updated"] + result["added"], "status": get_status()}
