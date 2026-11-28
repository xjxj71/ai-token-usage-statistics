import asyncio
import logging
from datetime import UTC, datetime

import aiosqlite

from backend.config import settings
from backend.db.data_migrations import (
    DATA_SCHEMA_VERSION,
    migrate_openclaw_deltas,
    migrate_token_semantics,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    agent             TEXT NOT NULL,
    model             TEXT NOT NULL,
    session_id        TEXT,
    project           TEXT NOT NULL DEFAULT '',
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_read_tokens  INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens   INTEGER DEFAULT 0,
    cost_usd          REAL DEFAULT 0.0,
    raw_data          TEXT
);

CREATE TABLE IF NOT EXISTS model_pricing (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    model             TEXT NOT NULL UNIQUE,
    input_price       REAL NOT NULL,
    output_price      REAL NOT NULL,
    cache_read_price  REAL DEFAULT 0.0,
    cache_write_price REAL DEFAULT 0.0,
    updated_at        TEXT NOT NULL,
    price_source      TEXT NOT NULL DEFAULT 'seed'
);

-- Daily aggregates kept when raw records are pruned by the retention job
-- (see backend/maintenance.py).  One row per (date, agent, model, project).
CREATE TABLE IF NOT EXISTS usage_daily (
    date              TEXT NOT NULL,
    agent             TEXT NOT NULL,
    model             TEXT NOT NULL,
    project           TEXT NOT NULL DEFAULT '',
    input_tokens      INTEGER NOT NULL DEFAULT 0,
    output_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL NOT NULL DEFAULT 0.0,
    call_count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, agent, model, project)
);

CREATE INDEX IF NOT EXISTS idx_token_usage_ts      ON token_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_token_usage_agent   ON token_usage(agent);
CREATE INDEX IF NOT EXISTS idx_token_usage_model   ON token_usage(model);
CREATE INDEX IF NOT EXISTS idx_token_usage_comp    ON token_usage(timestamp, agent, model);
CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(agent, session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_token_usage_unique
    ON token_usage(timestamp, agent, session_id, model);
"""

# user_version 1: promote cwd → project and reasoning_tokens out of raw_data
# into real columns (one-time backfill for databases created before this).
_SCHEMA_VERSION = 1

_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    global _db
    async with _db_lock:
        if _db is None:
            settings.db_path.parent.mkdir(parents=True, exist_ok=True)
            _db = await aiosqlite.connect(str(settings.db_path))
            _db.row_factory = aiosqlite.Row
            await _db.execute("PRAGMA journal_mode=WAL")
            await _db.execute("PRAGMA foreign_keys=ON")
        return _db


async def init_db() -> None:
    db = await get_db()
    await db.executescript(SCHEMA_SQL)
    await _migrate(db)
    await _seed_pricing(db)
    await sync_pricing_from_db(db)
    await db.commit()


async def sync_pricing_from_db(db: aiosqlite.Connection) -> None:
    """Apply the pricing table on top of the YAML defaults.

    The table is what the user sees and edits, so it is also what
    ``calculate_cost`` bills with (see ``model_pricing.overlay_pricing``).
    Call again after any change to ``model_pricing``.
    """
    from backend.pricing.model_pricing import overlay_pricing

    rows = await db.execute_fetchall(
        """SELECT model, input_price, output_price, cache_read_price, cache_write_price
           FROM model_pricing"""
    )
    overlay_pricing({
        r["model"]: {
            "input": r["input_price"],
            "output": r["output_price"],
            "cache_read": r["cache_read_price"],
            "cache_write": r["cache_write_price"],
        }
        for r in rows
    })


async def close_db() -> None:
    global _db
    async with _db_lock:
        if _db is not None:
            await _db.close()
            _db = None


async def _migrate(db: aiosqlite.Connection) -> None:
    """Bring databases created by older releases up to the current schema.

    Schema changes are additive: missing columns are added with ALTER TABLE
    (checked via PRAGMA table_info), while one-time data backfills are gated
    on PRAGMA user_version so each runs exactly once per database.
    """
    cols = {r["name"] for r in await db.execute_fetchall("PRAGMA table_info(token_usage)")}
    if "project" not in cols:
        await db.execute("ALTER TABLE token_usage ADD COLUMN project TEXT NOT NULL DEFAULT ''")
        logger.info("Migration: added token_usage.project")
    if "reasoning_tokens" not in cols:
        await db.execute(
            "ALTER TABLE token_usage ADD COLUMN reasoning_tokens INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("Migration: added token_usage.reasoning_tokens")

    pcols = {r["name"] for r in await db.execute_fetchall("PRAGMA table_info(model_pricing)")}
    if "price_source" not in pcols:
        await db.execute(
            "ALTER TABLE model_pricing ADD COLUMN price_source TEXT NOT NULL DEFAULT 'seed'"
        )
        logger.info("Migration: added model_pricing.price_source")

    version = (await db.execute_fetchall("PRAGMA user_version"))[0]["user_version"]
    if version < _SCHEMA_VERSION:
        await _backfill_project_and_reasoning(db)
        await db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        logger.info("Migration: schema upgraded to user_version=%d", _SCHEMA_VERSION)
        version = _SCHEMA_VERSION

    if version < 2:
        stats = await migrate_token_semantics(db)
        await db.execute("PRAGMA user_version = 2")
        logger.info("Migration: token semantics and pricing normalised (user_version=2): %s", stats)
        version = 2

    if version < DATA_SCHEMA_VERSION:
        stats = await migrate_openclaw_deltas(db)
        await db.execute(f"PRAGMA user_version = {DATA_SCHEMA_VERSION}")
        logger.info(
            "Migration: openclaw snapshots consolidated (user_version=%d): %s",
            DATA_SCHEMA_VERSION, stats,
        )


async def _backfill_project_and_reasoning(db: aiosqlite.Connection) -> None:
    """One-time backfill: derive project/reasoning_tokens from raw_data JSON."""
    import json

    from backend.db.models import project_from_cwd

    rows = await db.execute_fetchall(
        "SELECT id, raw_data FROM token_usage WHERE raw_data IS NOT NULL AND raw_data != ''"
    )
    updates: list[tuple[str, int, int]] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_data"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(raw, dict):
            continue

        project = project_from_cwd(raw.get("cwd"))
        reasoning = raw.get("reasoning_tokens") or 0
        if not isinstance(reasoning, int) or isinstance(reasoning, bool):
            try:
                reasoning = int(reasoning)
            except (TypeError, ValueError):
                reasoning = 0
        updates.append((project, reasoning, r["id"]))

    if updates:
        await db.executemany(
            "UPDATE token_usage SET project = ?, reasoning_tokens = ? WHERE id = ?",
            updates,
        )
        logger.info(
            "Migration: backfilled project/reasoning_tokens on %d of %d rows",
            len(updates), len(rows),
        )


def _is_placeholder(current: tuple[float, ...]) -> bool:
    """An all-zero pricing row: auto-inserted for a model that showed up
    before it had a price, not a price the user chose."""
    return not any(current)


async def _seed_pricing(db: aiosqlite.Connection) -> None:
    """Seed pricing from YAML.

    Models missing from the database are inserted.  Existing rows are the
    user's and are preserved — except an all-zero row, which is only a
    placeholder (see :func:`_is_placeholder`): it follows the YAML as soon as
    the YAML has a price for it.  Any non-zero price counts as the user's own.
    """
    from backend.pricing.model_pricing import load_yaml_pricing

    existing = {
        r["model"]: (
            r["input_price"], r["output_price"],
            r["cache_read_price"], r["cache_write_price"],
        )
        for r in await db.execute_fetchall(
            """SELECT model, input_price, output_price, cache_read_price, cache_write_price
               FROM model_pricing"""
        )
    }

    now = datetime.now(UTC).isoformat()
    inserts: list[tuple] = []
    upgrades: list[tuple] = []
    for model, prices in load_yaml_pricing().items():
        values = (
            prices["input"], prices["output"],
            prices["cache_read"], prices["cache_write"],
        )
        current = existing.get(model)
        if current is None:
            inserts.append((model, *values, now))
        elif _is_placeholder(current) and any(values):
            upgrades.append((*values, now, model))

    if inserts:
        await db.executemany(
            """INSERT INTO model_pricing
               (model, input_price, output_price, cache_read_price, cache_write_price, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            inserts,
        )
        logger.info("Seeded %d new models from YAML into pricing table", len(inserts))
    if upgrades:
        await db.executemany(
            """UPDATE model_pricing
               SET input_price = ?, output_price = ?, cache_read_price = ?, cache_write_price = ?,
                   updated_at = ?
               WHERE model = ?""",
            upgrades,
        )
        logger.info(
            "Priced %d placeholder rows from YAML (they were all zero)", len(upgrades),
        )
