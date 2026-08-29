from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime

import aiosqlite

logger = logging.getLogger(__name__)


_VALID_GROUP_BY = {"agent", "model", "agent_model", "project"}


def project_from_cwd(cwd: str | None) -> str:
    """Derive a short project name from a session working directory.

    Keeps only the last non-empty path segment so one repo maps to a single
    name regardless of where it lives (``D:\\repo\\foo`` and ``/home/me/foo``
    both → ``foo``).  Tolerates mixed separators and trailing slashes;
    empty input yields ``""``.
    """
    if not cwd:
        return ""
    segments = [s for s in re.split(r"[\\/]+", str(cwd).strip()) if s]
    return segments[-1] if segments else ""


def _validate_group_by(group_by: str) -> str:
    """Normalize and validate group_by to prevent SQL injection.

    The DB layer assembles the GROUP BY clause as a raw identifier, so it
    must never be interpolated from untrusted input.  Only the supported
    values are allowed; anything else falls back to ``"agent"`` to keep
    existing behaviour while remaining safe.
    """
    normalized = group_by.strip().lower()
    if normalized not in _VALID_GROUP_BY:
        logger.warning("Invalid group_by=%r; falling back to 'agent'", group_by)
        return "agent"
    return normalized


@dataclass(frozen=True)
class TokenRecord:
    timestamp: str
    agent: str
    model: str
    session_id: str = ""
    project: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
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
    project: str = ""
    reasoning_tokens: int = 0


async def _ensure_models_in_pricing(db: aiosqlite.Connection, models: set[str]) -> None:
    """确保模型在 model_pricing 表中存在。

    优先使用 YAML 配置中的定价；YAML 未收录的模型才以 0 价插入，
    避免已配置好价格的模型被 0 价行挡住（_seed_pricing 不覆盖已有行）。
    """
    if not models:
        return

    from backend.pricing.model_pricing import MODEL_PRICING

    pricing_lower = {k.lower(): v for k, v in MODEL_PRICING.items()}

    # Normalize to lowercase for case-insensitive matching
    models_lower = {m.lower() for m in models}

    rows = await db.execute_fetchall("SELECT model FROM model_pricing")
    existing = {r["model"].lower() for r in rows}
    new_models = models_lower - existing

    if new_models:
        now = datetime.now(UTC).isoformat()
        insert_rows = []
        for m in sorted(new_models):
            prices = pricing_lower.get(m)
            insert_rows.append(
                (
                    m,
                    prices["input"] if prices else 0.0,
                    prices["output"] if prices else 0.0,
                    prices.get("cache_read", 0) if prices else 0.0,
                    prices.get("cache_write", 0) if prices else 0.0,
                    now,
                )
            )
        await db.executemany(
            """INSERT INTO model_pricing
               (model, input_price, output_price, cache_read_price, cache_write_price, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            insert_rows,
        )
        logger.info("Auto-detected new models added to pricing: %s", ", ".join(sorted(new_models)))


async def insert_records(db: aiosqlite.Connection, records: Sequence[TokenRecord]) -> None:
    if not records:
        return
    # Normalize model names to lowercase
    normalized = [dataclass_replace(r, model=r.model.lower()) if r.model != r.model.lower() else r for r in records]
    await _ensure_models_in_pricing(db, {r.model for r in normalized})
    await db.executemany(
        """INSERT OR IGNORE INTO token_usage
           (timestamp, agent, model, session_id, project,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,
            cost_usd, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r.timestamp, r.agent, r.model, r.session_id, r.project,
                r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
                r.reasoning_tokens,
                r.cost_usd, r.raw_data,
            )
            for r in normalized
        ],
    )
    await db.commit()


async def upsert_records(db: aiosqlite.Connection, records: Sequence[TokenRecord]) -> None:
    """Insert new records or update existing ones.

    For collectors that track cumulative session-level data (e.g. Hermes),
    the same (timestamp, agent, session_id, model) row gets updated each
    poll cycle with the latest token counts until the session closes.
    """
    if not records:
        return
    # Normalize model names to lowercase
    normalized = [dataclass_replace(r, model=r.model.lower()) if r.model != r.model.lower() else r for r in records]
    await _ensure_models_in_pricing(db, {r.model for r in normalized})
    await db.executemany(
        """INSERT INTO token_usage
               (timestamp, agent, model, session_id, project,
                input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,
                cost_usd, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(timestamp, agent, session_id, model) DO UPDATE SET
                input_tokens         = excluded.input_tokens,
                output_tokens        = excluded.output_tokens,
                cache_read_tokens    = excluded.cache_read_tokens,
                cache_write_tokens   = excluded.cache_write_tokens,
                reasoning_tokens     = excluded.reasoning_tokens,
                cost_usd             = excluded.cost_usd,
                raw_data             = excluded.raw_data,
                project              = excluded.project""",
        [
            (
                r.timestamp, r.agent, r.model, r.session_id, r.project,
                r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
                r.reasoning_tokens,
                r.cost_usd, r.raw_data,
            )
            for r in normalized
        ],
    )
    await db.commit()


def _build_where(
    agents: list[str] | None = None,
    models: list[str] | None = None,
    projects: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    session_id: str | None = None,
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
    if projects:
        placeholders = ",".join("?" for _ in projects)
        clauses.append(f"project IN ({placeholders})")
        params.extend(projects)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if from_ts:
        clauses.append("timestamp >= ?")
        params.append(from_ts)
    if to_ts:
        clauses.append("timestamp < ?")
        params.append(to_ts)

    where = " AND ".join(clauses)
    return ([where] if where else []), params


async def _usage_source(db: aiosqlite.Connection) -> str:
    """FROM-clause source for aggregate reads, covering archived history.

    Once the retention job (backend/maintenance.py) has archived days into
    ``usage_daily``, aggregate queries must UNION both tables or long-range
    views would silently lose everything older than the retention window.
    Archived rows get a synthetic midday UTC timestamp so the Shanghai-day
    bucketing and range filters keep working, and an empty session_id so
    they never leak into session-level reads.
    """
    rows = await db.execute_fetchall("SELECT 1 FROM usage_daily LIMIT 1")
    if not rows:
        return "token_usage"
    return """(
        SELECT timestamp, agent, model, session_id, project,
               input_tokens, output_tokens, cache_read_tokens,
               cache_write_tokens, reasoning_tokens, cost_usd
        FROM token_usage
        UNION ALL
        SELECT date || 'T12:00:00Z', agent, model, '', project,
               input_tokens, output_tokens, cache_read_tokens,
               cache_write_tokens, reasoning_tokens, cost_usd
        FROM usage_daily
    )"""


async def fetch_summary(
    db: aiosqlite.Connection,
    agents: list[str] | None = None,
    models: list[str] | None = None,
    projects: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    group_by: str = "agent",
) -> list[SummaryRow]:
    group_by = _validate_group_by(group_by)

    wheres, params = _build_where(agents, models, projects, from_ts, to_ts)
    where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    source = await _usage_source(db)

    if group_by == "agent":
        # Group by agent — model/project become display values (empty string).
        select_agent = "t.agent"
        select_model = "'' AS model"
        select_project = "'' AS project"
        group_clause = "t.agent"
    elif group_by == "project":
        select_agent = "'' AS agent"
        select_model = "'' AS model"
        select_project = "t.project"
        group_clause = "t.project"
    else:
        # Group by model — agent/project become display values (empty string).
        select_agent = "'' AS agent"
        select_model = "t.model"
        select_project = "'' AS project"
        group_clause = "t.model"

    rows = await db.execute_fetchall(
        f"""SELECT {select_agent}, {select_model}, {select_project},
               SUM(t.input_tokens) as input_tokens,
               SUM(t.output_tokens) as output_tokens,
               SUM(t.cache_read_tokens) as cache_read_tokens,
               SUM(t.cache_write_tokens) as cache_write_tokens,
               SUM(t.reasoning_tokens) as reasoning_tokens,
               SUM(
                   t.input_tokens      * COALESCE(p.input_price, 0)      / 1000000.0 +
                   t.output_tokens     * COALESCE(p.output_price, 0)     / 1000000.0 +
                   t.cache_read_tokens * COALESCE(p.cache_read_price, 0) / 1000000.0 +
                   t.cache_write_tokens* COALESCE(p.cache_write_price,0) / 1000000.0
               ) as cost_usd,
               COUNT(*) as call_count
           FROM {source} t
           LEFT JOIN model_pricing p ON t.model = p.model
           {where_sql}
           GROUP BY {group_clause}
           ORDER BY cost_usd DESC""",
        params,
    )

    return [
        SummaryRow(
            agent=r["agent"],
            model=r["model"],
            project=r["project"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_write_tokens=r["cache_write_tokens"],
            cost_usd=round(r["cost_usd"], 6),
            call_count=r["call_count"],
            reasoning_tokens=r["reasoning_tokens"] or 0,
        )
        for r in rows
    ]


async def fetch_usage_page(
    db: aiosqlite.Connection,
    page: int = 1,
    limit: int = 50,
    agents: list[str] | None = None,
    models: list[str] | None = None,
    projects: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    session_id: str | None = None,
) -> tuple[list[TokenRecord], int]:
    wheres, params = _build_where(agents, models, projects, from_ts, to_ts, session_id)
    where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""

    total_row = await db.execute_fetchall(
        f"SELECT COUNT(*) as cnt FROM token_usage {where_sql}", params
    )
    total = total_row[0]["cnt"]

    offset = (page - 1) * limit
    rows = await db.execute_fetchall(
        f"""SELECT t.id, t.timestamp, t.agent, t.model, t.session_id, t.project,
                   t.input_tokens, t.output_tokens, t.cache_read_tokens, t.cache_write_tokens,
                   t.reasoning_tokens, t.raw_data,
                   (t.input_tokens      * COALESCE(p.input_price, 0)      / 1000000.0 +
                    t.output_tokens     * COALESCE(p.output_price, 0)     / 1000000.0 +
                    t.cache_read_tokens * COALESCE(p.cache_read_price, 0) / 1000000.0 +
                    t.cache_write_tokens* COALESCE(p.cache_write_price,0) / 1000000.0
                   ) as cost_usd
           FROM token_usage t
           LEFT JOIN model_pricing p ON t.model = p.model
           {where_sql}
           ORDER BY t.timestamp DESC
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
            project=r["project"] or "",
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_write_tokens=r["cache_write_tokens"],
            reasoning_tokens=r["reasoning_tokens"] or 0,
            cost_usd=r["cost_usd"],
        )
        for r in rows
    ]

    return records, total


async def fetch_distinct_agents(db: aiosqlite.Connection) -> list[str]:
    source = await _usage_source(db)
    rows = await db.execute_fetchall(f"SELECT DISTINCT agent FROM {source} ORDER BY agent")
    return [r["agent"] for r in rows]


async def fetch_distinct_models(db: aiosqlite.Connection) -> list[str]:
    source = await _usage_source(db)
    rows = await db.execute_fetchall(f"SELECT DISTINCT model FROM {source} ORDER BY model")
    return [r["model"] for r in rows]


async def fetch_distinct_projects(db: aiosqlite.Connection) -> list[str]:
    source = await _usage_source(db)
    rows = await db.execute_fetchall(
        f"SELECT DISTINCT project FROM {source} WHERE project != '' ORDER BY project"
    )
    return [r["project"] for r in rows]


@dataclass(frozen=True)
class SessionRow:
    agent: str
    session_id: str
    project: str
    models: list[str]
    first_ts: str
    last_ts: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    cost_usd: float
    call_count: int


async def fetch_sessions_page(
    db: aiosqlite.Connection,
    page: int = 1,
    limit: int = 20,
    agents: list[str] | None = None,
    models: list[str] | None = None,
    projects: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> tuple[list[SessionRow], int]:
    """Aggregate usage per (agent, session_id) for the session drill-down view.

    Records without a session_id are excluded; sessions are ordered by most
    recent activity.  Cost is recomputed through the pricing join like every
    other read path.
    """
    wheres, params = _build_where(agents, models, projects, from_ts, to_ts)
    clauses = list(wheres) + ["t.session_id != ''"]
    where_sql = f"WHERE {' AND '.join(clauses)}"

    total_row = await db.execute_fetchall(
        f"""SELECT COUNT(*) as cnt FROM (
                SELECT t.agent, t.session_id FROM token_usage t {where_sql}
                GROUP BY t.agent, t.session_id
            )""",
        params,
    )
    total = total_row[0]["cnt"]

    offset = (page - 1) * limit
    rows = await db.execute_fetchall(
        f"""SELECT t.agent, t.session_id,
               MAX(t.project) as project,
               GROUP_CONCAT(DISTINCT t.model) as models,
               MIN(t.timestamp) as first_ts,
               MAX(t.timestamp) as last_ts,
               SUM(t.input_tokens) as input_tokens,
               SUM(t.output_tokens) as output_tokens,
               SUM(t.cache_read_tokens) as cache_read_tokens,
               SUM(t.cache_write_tokens) as cache_write_tokens,
               SUM(t.reasoning_tokens) as reasoning_tokens,
               SUM(
                   t.input_tokens      * COALESCE(p.input_price, 0)      / 1000000.0 +
                   t.output_tokens     * COALESCE(p.output_price, 0)     / 1000000.0 +
                   t.cache_read_tokens * COALESCE(p.cache_read_price, 0) / 1000000.0 +
                   t.cache_write_tokens* COALESCE(p.cache_write_price,0) / 1000000.0
               ) as cost_usd,
               COUNT(*) as call_count
           FROM token_usage t
           LEFT JOIN model_pricing p ON t.model = p.model
           {where_sql}
           GROUP BY t.agent, t.session_id
           ORDER BY last_ts DESC
           LIMIT ? OFFSET ?""",
        params + [limit, offset],
    )

    sessions = [
        SessionRow(
            agent=r["agent"],
            session_id=r["session_id"],
            project=r["project"] or "",
            models=[m for m in (r["models"] or "").split(",") if m],
            first_ts=r["first_ts"],
            last_ts=r["last_ts"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_write_tokens=r["cache_write_tokens"],
            reasoning_tokens=r["reasoning_tokens"] or 0,
            cost_usd=round(r["cost_usd"], 6),
            call_count=r["call_count"],
        )
        for r in rows
    ]
    return sessions, total


async def fetch_trend(
    db: aiosqlite.Connection,
    group_by: str = "agent",
    granularity: str = "day",
    from_ts: str | None = None,
    to_ts: str | None = None,
    agents: list[str] | None = None,
    models: list[str] | None = None,
) -> list[dict]:
    """Fetch daily/hourly token usage trend, grouped by time period + agent or model.

    Args:
        granularity: ``"day"`` → group by date (``substr(ts, 1, 10)``).
                     ``"hour"`` → group by hour (``substr(ts, 1, 13)``).

    Returns rows with: date, name (agent or model), total_tokens.
    """
    group_by = _validate_group_by(group_by)

    wheres, params = _build_where(agents, models, from_ts=from_ts, to_ts=to_ts)

    group_col = "agent" if group_by == "agent" else "model"
    name_col = group_col

    if granularity == "hour":
        # Convert UTC timestamp to Shanghai time (UTC+8) before bucketing
        # SQLite datetime() expects "YYYY-MM-DD HH:MM:SS" format
        date_expr = (
            "replace(substr(datetime(replace(substr(timestamp,1,19),'T',' '),'+8 hours'),1,13),' ','T')"
        )
    else:
        # Daily: Shanghai date from UTC+8 conversion
        date_expr = (
            "substr(datetime(replace(substr(timestamp,1,19),'T',' '),'+8 hours'),1,10)"
        )

    where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    source = await _usage_source(db)

    rows = await db.execute_fetchall(
        f"""SELECT {date_expr} as date,
                   {name_col} as name,
                   SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens) as total_tokens
            FROM {source}
            {where_sql}
            GROUP BY date, {name_col}
            ORDER BY date, {name_col}""",
        params,
    )

    return [
        {
            "date": r["date"],
            "name": r["name"],
            "total_tokens": r["total_tokens"],
        }
        for r in rows
    ]


@dataclass(frozen=True)
class CacheRatioRow:
    agent: str
    model: str
    total_tokens: int
    cache_read_tokens: int
    cache_ratio: float  # 0.0 ~ 1.0


async def fetch_cache_ratio(
    db: aiosqlite.Connection,
    agents: list[str] | None = None,
    models: list[str] | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    group_by: str = "agent",
) -> list[CacheRatioRow]:
    """Fetch cache hit ratio grouped by agent, model, or agent+model.

    Cache ratio = cache_read_tokens / (input_tokens + cache_read_tokens + cache_write_tokens).
    """
    wheres, params = _build_where(agents, models, from_ts=from_ts, to_ts=to_ts)
    where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    source = await _usage_source(db)

    if group_by == "agent":
        select_agent = "t.agent"
        select_model = "'' AS model"
        group_clause = "t.agent"
    elif group_by == "model":
        select_agent = "'' AS agent"
        select_model = "t.model"
        group_clause = "t.model"
    else:  # agent_model
        select_agent = "t.agent"
        select_model = "t.model"
        group_clause = "t.agent, t.model"

    rows = await db.execute_fetchall(
        f"""SELECT {select_agent}, {select_model},
               SUM(t.input_tokens + t.output_tokens + t.cache_read_tokens + t.cache_write_tokens) as total_tokens,
               SUM(t.cache_read_tokens) as cache_read_tokens
           FROM {source} t
           {where_sql}
           GROUP BY {group_clause}
           HAVING total_tokens > 0
           ORDER BY cache_read_tokens * 1.0 / total_tokens DESC""",
        params,
    )

    return [
        CacheRatioRow(
            agent=r["agent"],
            model=r["model"],
            total_tokens=r["total_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_ratio=round(r["cache_read_tokens"] / r["total_tokens"], 4) if r["total_tokens"] > 0 else 0.0,
        )
        for r in rows
    ]
