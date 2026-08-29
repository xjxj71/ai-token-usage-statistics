from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Query

from backend.api.range_utils import resolve_range
from backend.db import database as db_module
from backend.db.models import fetch_sessions_page

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])


@router.get("/sessions")
async def get_sessions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    agent: str | None = Query(None),
    model: str | None = Query(None),
    project: str | None = Query(None),
    range_key: str | None = Query(None, alias="range"),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    """Session-level usage aggregates, newest activity first.

    Sessions group records by (agent, session_id); use ``GET /api/usage``
    with the ``session_id`` parameter for a session's individual records.
    """
    db = await db_module.get_db()

    agents = agent.split(",") if agent else None
    models = model.split(",") if model else None
    projects = project.split(",") if project else None

    if range_key:
        from_ts, to_ts = resolve_range(range_key, from_date, to_date)
    else:
        from_ts, to_ts = from_date, to_date

    sessions, total = await fetch_sessions_page(
        db,
        page=page,
        limit=limit,
        agents=agents,
        models=models,
        projects=projects,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    return {
        "items": [asdict(s) for s in sessions],
        "total": total,
        "page": page,
    }
