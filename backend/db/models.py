from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import aiosqlite


@dataclass(frozen=True)
class TokenRecord:
    timestamp: str
    agent: str
    model: str
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    raw_data: str = ""
    id: int | None = None


@dataclass(frozen=True)
class SummaryRow:
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    call_count: int


async def insert_records(db: aiosqlite.Connection, records: Sequence[TokenRecord]) -> None:
    if not records:
        return
    await db.executemany(
        """INSERT INTO token_usage
           (timestamp, agent, model, session_id,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            cost_usd, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r.timestamp, r.agent, r.model, r.session_id,
                r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
                r.cost_usd, r.raw_data,
            )
            for r in records
        ],
    )
    await db.commit()


def _build_where(
    agents: list[str] | None = None,
    models: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> tuple[list[str], list[str | int]]:
    clauses: list[str] = []
    params: list[str | int] = []

    if agents:
        placeholders = ",".join("?" for _ in agents)
        clauses.append(f"agent IN ({placeholders})")
        params.extend(agents)
    if models:
        placeholders = ",".join("?" for _ in models)
        clauses.append(f"model IN ({placeholders})")
        params.extend(models)
    if from_ts:
        clauses.append("timestamp >= ?")
        params.append(from_ts)
    if to_ts:
        clauses.append("timestamp < ?")
        params.append(to_ts)

    where = " AND ".join(clauses)
    return ([where] if where else []), params


async def fetch_summary(
    db: aiosqlite.Connection,
    agents: list[str] | None = None,
    models: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    group_by: str = "agent",
) -> list[SummaryRow]:
    wheres, params = _build_where(agents, models, from_ts, to_ts)
    where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""

    group_col = group_by if group_by in ("agent", "model") else "agent"
    rows = await db.execute_fetchall(
        f"""SELECT agent, model,
               SUM(input_tokens) as input_tokens,
               SUM(output_tokens) as output_tokens,
               SUM(cache_read_tokens) as cache_read_tokens,
               SUM(cache_write_tokens) as cache_write_tokens,
               SUM(cost_usd) as cost_usd,
               COUNT(*) as call_count
           FROM token_usage
           {where_sql}
           GROUP BY {group_col}, model
           ORDER BY cost_usd DESC""",
        params,
    )

    return [
        SummaryRow(
            agent=r["agent"],
            model=r["model"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_write_tokens=r["cache_write_tokens"],
            cost_usd=round(r["cost_usd"], 6),
            call_count=r["call_count"],
        )
        for r in rows
    ]


async def fetch_usage_page(
    db: aiosqlite.Connection,
    page: int = 1,
    limit: int = 50,
    agents: list[str] | None = None,
    models: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> tuple[list[TokenRecord], int]:
    wheres, params = _build_where(agents, models, from_ts, to_ts)
    where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""

    total_row = await db.execute_fetchall(
        f"SELECT COUNT(*) as cnt FROM token_usage {where_sql}", params
    )
    total = total_row[0]["cnt"]

    offset = (page - 1) * limit
    rows = await db.execute_fetchall(
        f"""SELECT * FROM token_usage
           {where_sql}
           ORDER BY timestamp DESC
           LIMIT ? OFFSET ?""",
        params + [limit, offset],
    )

    records = [
        TokenRecord(
            id=r["id"],
            timestamp=r["timestamp"],
            agent=r["agent"],
            model=r["model"],
            session_id=r["session_id"] or "",
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_write_tokens=r["cache_write_tokens"],
            cost_usd=r["cost_usd"],
        )
        for r in rows
    ]

    return records, total


async def fetch_distinct_agents(db: aiosqlite.Connection) -> list[str]:
    rows = await db.execute_fetchall("SELECT DISTINCT agent FROM token_usage ORDER BY agent")
    return [r["agent"] for r in rows]


async def fetch_distinct_models(db: aiosqlite.Connection) -> list[str]:
    rows = await db.execute_fetchall("SELECT DISTINCT model FROM token_usage ORDER BY model")
    return [r["model"] for r in rows]
