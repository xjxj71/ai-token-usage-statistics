import asyncio
import logging
from datetime import datetime, timezone

import aiosqlite

from backend.config import settings

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    agent             TEXT NOT NULL,
    model             TEXT NOT NULL,
    session_id        TEXT,
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_read_tokens  INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
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
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_usage_ts    ON token_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_token_usage_agent ON token_usage(agent);
CREATE INDEX IF NOT EXISTS idx_token_usage_model ON token_usage(model);
CREATE INDEX IF NOT EXISTS idx_token_usage_comp  ON token_usage(timestamp, agent, model);
CREATE UNIQUE INDEX IF NOT EXISTS idx_token_usage_unique
    ON token_usage(timestamp, agent, session_id, model);
"""

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
    await _seed_pricing(db)
    await db.commit()


async def close_db() -> None:
    global _db
    async with _db_lock:
        if _db is not None:
            await _db.close()
            _db = None


async def _seed_pricing(db: aiosqlite.Connection) -> None:
    """Seed pricing from YAML.

    Only inserts models that do NOT yet exist in the database.
    Existing rows (including user-customized prices) are preserved.
    """
    from backend.pricing.model_pricing import MODEL_PRICING, load_pricing

    # Ensure pricing is loaded from YAML
    if not MODEL_PRICING:
        load_pricing()

    # Fetch existing models to avoid overwriting user customizations
    rows = await db.execute_fetchall("SELECT model FROM model_pricing")
    existing = {r["model"] for r in rows}

    now = datetime.now(timezone.utc).isoformat()
    new_models = []
    for model, prices in MODEL_PRICING.items():
        if model not in existing:
            new_models.append((
                model, prices["input"], prices["output"],
                prices.get("cache_read", 0), prices.get("cache_write", 0), now,
            ))

    if new_models:
        await db.executemany(
            """INSERT INTO model_pricing
               (model, input_price, output_price, cache_read_price, cache_write_price, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            new_models,
        )
        logger.info("Seeded %d new models from YAML into pricing table", len(new_models))
