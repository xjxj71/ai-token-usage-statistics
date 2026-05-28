from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import database as db_module
from backend.db.models import fetch_distinct_agents, fetch_distinct_models
from backend.api.constants import IGNORED_MODELS, SUPPORTED_AGENTS

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

    # 获取 model_pricing 表中所有已知模型
    rows = await db.execute_fetchall("SELECT model FROM model_pricing ORDER BY model")
    known_models = {r["model"] for r in rows}

    # 只返回：在 token_usage 中出现过 + 在 model_pricing 中存在 + 不在黑名单中
    filtered = [
        m for m in used_models
        if m.lower() not in IGNORED_MODELS and m in known_models
    ]

    # 获取完整定价信息
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

    # 只返回过滤后的模型，附上定价信息
    result = []
    for m in filtered:
        entry = pricing.get(m, {"model": m})
        result.append(entry)

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


class PricingUpdate(BaseModel):
    input_price: float = Field(ge=0)
    output_price: float = Field(ge=0)
    cache_read_price: float = Field(default=0.0, ge=0)
    cache_write_price: float = Field(default=0.0, ge=0)


@router.put("/pricing/{model:path}")
async def update_pricing(model: str, body: PricingUpdate):
    """更新指定模型的自定义定价。"""
    db = await db_module.get_db()

    # 检查模型是否存在
    row = await db.execute_fetchall(
        "SELECT model FROM model_pricing WHERE model = ?", (model,)
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"模型 '{model}' 不存在")

    now = datetime.now(timezone.utc).isoformat()
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
async def refresh_pricing():
    """从 OpenRouter API 一键获取最新模型定价，更新数据库。"""
    import json as json_mod
    import urllib.request
    import urllib.error

    db = await db_module.get_db()

    # 获取当前数据库中已有的模型
    existing_rows = await db.execute_fetchall("SELECT model FROM model_pricing")
    existing_models = {r["model"] for r in existing_rows}

    updated = 0
    added = 0

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
        now = datetime.now(timezone.utc).isoformat()

        for m in models:
            model_id = m.get("id", "")
            if not model_id:
                continue

            pricing = m.get("pricing", {})
            if not pricing:
                continue

            # OpenRouter pricing 是每 token 价格，转换为每 M token
            input_price = float(pricing.get("prompt", 0)) * 1_000_000
            output_price = float(pricing.get("completion", 0)) * 1_000_000
            cache_read_price = float(pricing.get("input_cache_read", 0)) * 1_000_000
            cache_write_price = float(pricing.get("input_cache_write", 0)) * 1_000_000

            if model_id in existing_models:
                await db.execute(
                    """UPDATE model_pricing
                       SET input_price = ?, output_price = ?,
                           cache_read_price = ?, cache_write_price = ?, updated_at = ?
                       WHERE model = ?""",
                    (input_price, output_price, cache_read_price, cache_write_price, now, model_id),
                )
                updated += 1
            else:
                await db.execute(
                    """INSERT INTO model_pricing (model, input_price, output_price, cache_read_price, cache_write_price, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (model_id, input_price, output_price, cache_read_price, cache_write_price, now),
                )
                added += 1

        await db.commit()

    except urllib.error.URLError as e:
        logger.error("OpenRouter API 请求失败: %s", e)
        raise HTTPException(status_code=502, detail=f"OpenRouter API 请求失败: {str(e)}")
    except Exception as e:
        logger.error("刷新定价失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"刷新定价失败: {str(e)}")

    return {"updated": updated, "added": added, "total": updated + added}
