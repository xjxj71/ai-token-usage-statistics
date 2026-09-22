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
               cache_read_price = ?, cache_write_price = ?, updated_at = ?
           WHERE model = ?""",
        (body.input_price, body.output_price,
         body.cache_read_price, body.cache_write_price, now, model),
    )
    await db.commit()

    return {
        "model": model,
        "input_price": body.input_price,
        "output_price": body.output_price,
        "cache_read_price": body.cache_read_price,
        "cache_write_price": body.cache_write_price,
        "updated_at": now,
    }


@router.post("/pricing/refresh")
async def refresh_pricing(request: Request):
    """从 OpenRouter API 一键获取最新模型定价，更新数据库（仅本机或携带有效 API Key）。"""
    require_local_or_key(request)
    import json as json_mod
    import urllib.error
    import urllib.request

    db = await db_module.get_db()

    # 获取当前数据库中已有的模型
    existing_rows = await db.execute_fetchall("SELECT model FROM model_pricing")
    existing_models = {r["model"] for r in existing_rows}

    updated = 0

    try:
        def _fetch():
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"User-Agent": "ai-token-usage/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json_mod.loads(resp.read().decode("utf-8"))

        import asyncio
        data = await asyncio.to_thread(_fetch)

        models = data.get("data", [])
        now = datetime.now(UTC).isoformat()

        # Only refresh models already tracked in our table — importing all
        # OpenRouter models (hundreds) would pollute /api/pricing and the
        # model dropdown. New models get seeded from config/model_pricing.yaml
        # by _ensure_models_in_pricing instead.
        updates: list[tuple[float, float, float, float, str, str]] = []

        for m in models:
            model_id = m.get("id", "")
            if not model_id or model_id not in existing_models:
                continue

            pricing = m.get("pricing", {})
            if not pricing:
                continue

            # OpenRouter pricing 是每 token 价格，转换为每 M token
            try:
                input_price = float(pricing.get("prompt", 0)) * 1_000_000
                output_price = float(pricing.get("completion", 0)) * 1_000_000
                cache_read_price = float(pricing.get("input_cache_read", 0)) * 1_000_000
                cache_write_price = float(pricing.get("input_cache_write", 0)) * 1_000_000
            except (TypeError, ValueError):
                logger.debug("Skipping model %s: non-numeric pricing", model_id)
                continue

            updates.append(
                (input_price, output_price, cache_read_price, cache_write_price, now, model_id)
            )

        if updates:
            await db.executemany(
                """UPDATE model_pricing
                   SET input_price = ?, output_price = ?,
                       cache_read_price = ?, cache_write_price = ?, updated_at = ?
                   WHERE model = ?""",
                updates,
            )
            await db.commit()

        updated = len(updates)

    except urllib.error.URLError as e:
        logger.error("OpenRouter API 请求失败: %s", e)
        raise HTTPException(status_code=502, detail=f"OpenRouter API 请求失败: {e!s}")
    except Exception:
        logger.exception("刷新定价失败")
        raise HTTPException(status_code=500, detail="刷新定价失败")

    return {"updated": updated, "added": 0, "total": updated}
