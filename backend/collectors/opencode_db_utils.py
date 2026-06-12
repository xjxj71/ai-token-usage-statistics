"""Shared SQLite parsing utilities for OpenCode-family collectors.

MiMoCode and OpenCode use the same database schema (MiMoCode is a fork of OpenCode).
Token usage data is stored in the `message` table as JSON in the `data` field.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


def _parse_timestamp_ms(ts_ms: int | None) -> str:
    """Convert millisecond epoch timestamp to ISO format string."""
    if not ts_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, OSError):
        return ""


def extract_token_records(
    db_path: str | Path,
    agent_name: str,
    last_timestamp_ms: int = 0,
) -> tuple[list[TokenRecord], int]:
    """Extract token usage records from an OpenCode-family SQLite database.

    Args:
        db_path: Path to the SQLite database file
        agent_name: Agent name to set on records (e.g., "mimo-code", "opencode")
        last_timestamp_ms: Only process messages after this timestamp (ms epoch)

    Returns:
        (records, max_timestamp_ms) - List of TokenRecord and the latest timestamp seen
    """
    db_path = Path(db_path)
    if not db_path.exists():
        logger.debug("%s: database not found at %s", agent_name, db_path)
        return [], last_timestamp_ms

    records: list[TokenRecord] = []
    max_ts_ms = last_timestamp_ms

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query assistant messages with token usage data
        query = """
            SELECT id, session_id, time_created, data
            FROM message
            WHERE data LIKE '%"role":"assistant"%'
              AND data LIKE '%"tokens"%'
              AND time_created > ?
            ORDER BY time_created ASC
        """

        cursor.execute(query, (last_timestamp_ms,))
        rows = cursor.fetchall()

        for row in rows:
            try:
                data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Only process assistant messages
            if data.get("role") != "assistant":
                continue

            tokens = data.get("tokens")
            if not tokens:
                continue

            # Extract token counts
            input_tokens = tokens.get("input", 0) or 0
            output_tokens = tokens.get("output", 0) or 0
            reasoning_tokens = tokens.get("reasoning", 0) or 0
            cache = tokens.get("cache", {})
            cache_read = cache.get("read", 0) or 0
            cache_write = cache.get("write", 0) or 0

            # Skip all-zero records
            if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
                continue

            # Extract model info
            model_id = data.get("modelID", "unknown")
            provider_id = data.get("providerID", "")
            model = f"{provider_id}/{model_id}" if provider_id and model_id != "unknown" else model_id

            # Extract timestamp
            time_data = data.get("time", {})
            created_ms = time_data.get("created", row["time_created"])
            timestamp = _parse_timestamp_ms(created_ms)

            if not timestamp:
                continue

            # Calculate cost
            cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

            # Build raw metadata
            raw_data = json.dumps({
                "session_id": row["session_id"],
                "message_id": row["id"],
                "provider_id": provider_id,
                "model_id": model_id,
                "reasoning_tokens": reasoning_tokens,
            }, ensure_ascii=False)

            record = TokenRecord(
                timestamp=timestamp,
                agent=agent_name,
                model=model.lower(),
                session_id=row["session_id"] or "",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=round(cost, 6),
                raw_data=raw_data,
            )
            records.append(record)

            # Track max timestamp
            if created_ms and created_ms > max_ts_ms:
                max_ts_ms = created_ms

        conn.close()

    except sqlite3.Error as e:
        logger.error("%s: database error: %s", agent_name, e)
        return [], last_timestamp_ms

    logger.info("%s: extracted %d records from database", agent_name, len(records))
    return records, max_ts_ms
