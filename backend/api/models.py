from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db import database as db_module
from backend.db.models import fetch_distinct_agents, fetch_distinct_models

logger = logging.getLogger(__name__)

from backend.api.constants import IGNORED_MODELS, SUPPORTED_AGENTS

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
        entry = pricing.pop(m, {"model": m})
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
    input_price: float
    output_price: float
    cache_read_price: float = 0.0
    cache_write_price: float = 0.0


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
