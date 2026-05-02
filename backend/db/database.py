import aiosqlite
from pathlib import Path

from backend.config import settings

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
"""

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
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
    if _db is not None:
        await _db.close()
        _db = None


async def _seed_pricing(db: aiosqlite.Connection) -> None:
    from backend.pricing.model_pricing import MODEL_PRICING

    count = await db.execute_fetchall("SELECT COUNT(*) FROM model_pricing")
    if count[0][0] > 0:
        return

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for model, prices in MODEL_PRICING.items():
        await db.execute(
            """INSERT OR IGNORE INTO model_pricing
               (model, input_price, output_price, cache_read_price, cache_write_price, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (model, prices["input"], prices["output"],
             prices.get("cache_read", 0), prices.get("cache_write", 0), now),
        )
