from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Query

from backend.api.range_utils import resolve_range
from backend.db import database as db_module
from backend.db.models import fetch_usage_page

router = APIRouter(tags=["usage"])


@router.get("/usage")
async def get_usage(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    agent: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    range_key: Optional[str] = Query(None, alias="range"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    db = await db_module.get_db()

    agents = agent.split(",") if agent else None
    models = model.split(",") if model else None

    # Use centralized range resolution when range_key is provided
    if range_key:
        from_ts, to_ts = resolve_range(range_key, from_date, to_date)
    else:
        from_ts, to_ts = from_date, to_date

    records, total = await fetch_usage_page(
        db,
        page=page,
        limit=limit,
        agents=agents,
        models=models,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    return {
        "items": [asdict(r) for r in records],
        "total": total,
        "page": page,
    }
