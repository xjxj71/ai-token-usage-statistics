from __future__ import annotations

from fastapi import APIRouter

from backend.db import database as db_module
from backend.db.models import fetch_distinct_agents, fetch_distinct_models

router = APIRouter(tags=["models"])


@router.get("/models")
async def get_models():
    db = await db_module.get_db()
    used_models = await fetch_distinct_models(db)

    rows = await db.execute_fetchall("SELECT * FROM model_pricing ORDER BY model")
    pricing = {
        r["model"]: {
            "model": r["model"],
            "input_price": r["input_price"],
            "output_price": r["output_price"],
            "cache_read_price": r["cache_read_price"],
            "cache_write_price": r["cache_write_price"],
        }
        for r in rows
    }

    # Merge: models seen in usage data get pricing info if available
    result = []
    for m in used_models:
        entry = pricing.pop(m, {"model": m})
        result.append(entry)

    # Append remaining priced models not yet seen in usage
    for entry in pricing.values():
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
    return agents
