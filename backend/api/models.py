from __future__ import annotations

from fastapi import APIRouter

from backend.db import database as db_module
from backend.db.models import fetch_distinct_agents, fetch_distinct_models

router = APIRouter(tags=["models"])


@router.get("/models")
async def get_models():
    db = await db_module.get_db()
    models = await fetch_distinct_models(db)

    rows = await db.execute_fetchall("SELECT * FROM model_pricing ORDER BY model")
    pricing = [
        {
            "model": r["model"],
            "input_price": r["input_price"],
            "output_price": r["output_price"],
            "cache_read_price": r["cache_read_price"],
            "cache_write_price": r["cache_write_price"],
        }
        for r in rows
    ]

    return pricing


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
