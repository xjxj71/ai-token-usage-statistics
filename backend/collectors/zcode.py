"""ZCode CLI token usage collector.

Reads the ``model_usage`` table from ZCode's local usage database
(``~/.zcode/cli/db/db.sqlite``).  ZCode records one row per model request
with full token accounting (input / output / cache read / cache write),
so the table can be polled passively — zero intrusion, no hooks.

Watermark: ``completed_at`` (epoch ms).  Rows are only counted once their
request has finished — while ``status`` is ``running`` the token counts are
not final yet, so filtering on ``completed_at IS NOT NULL`` picks them up on
a later poll automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from backend.collectors.base import BaseCollector
from backend.collectors.sqlite_utils import copy_sqlite_with_wal, remove_sqlite_temp
from backend.config import settings
from backend.db.models import TokenRecord, project_from_cwd
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


def _fmt_ms_z(dt: datetime) -> str:
    """Format a UTC datetime as ISO with milliseconds, ``Z``-suffixed.

    Millisecond precision keeps distinct requests in the same second from
    colliding on the (timestamp, agent, session_id, model) unique index;
    the ``Z`` suffix matches the format used across the database.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def extract_model_usage(
    db_path: str | Path,
    last_completed_ms: int,
    agent_name: str,
) -> tuple[list[TokenRecord], int]:
    """Read completed model requests past the watermark from a db snapshot.

    Blocking — call via ``asyncio.to_thread``.  Returns
    ``(records, new_watermark)``; the watermark only advances (never
    regresses when no rows are found).
    """
    records: list[TokenRecord] = []
    max_completed_ms = last_completed_ms

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT m.id, m.session_id, m.turn_id, m.query_source, m.agent,
                   m.attempt_index, m.model_id,
                   m.started_at, m.completed_at,
                   m.input_tokens, m.output_tokens, m.reasoning_tokens,
                   m.cache_creation_input_tokens, m.cache_read_input_tokens,
                   s.directory
            FROM model_usage m
            LEFT JOIN session s ON s.id = m.session_id
            WHERE m.completed_at IS NOT NULL AND m.completed_at > ?
            ORDER BY m.completed_at
            """,
            (last_completed_ms,),
        ).fetchall()
    except sqlite3.Error as e:
        # Older ZCode versions may lack the table — warn and keep watermark.
        logger.warning("ZCode: failed to query model_usage: %s", e)
        if conn is not None:
            conn.close()
        return records, last_completed_ms
    finally:
        if conn is not None:
            conn.close()

    for row in rows:
        input_tokens = row["input_tokens"] or 0
        output_tokens = row["output_tokens"] or 0
        cache_read = row["cache_read_input_tokens"] or 0
        cache_write = row["cache_creation_input_tokens"] or 0

        # Skip all-zero rows (errored calls that never billed tokens)
        if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
            continue

        model = (row["model_id"] or "unknown").lower()
        started_ms = row["started_at"] or row["completed_at"]
        try:
            ts = _fmt_ms_z(datetime.fromtimestamp(started_ms / 1000.0, tz=UTC))
        except (ValueError, OSError, OverflowError):
            logger.debug("ZCode: skipping row with bad timestamp %s", started_ms)
            continue

        cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

        raw = json.dumps(
            {
                "usage_id": row["id"],
                "turn_id": row["turn_id"],
                "query_source": row["query_source"],
                "sub_agent": row["agent"],
                "attempt_index": row["attempt_index"],
                "reasoning_tokens": row["reasoning_tokens"] or 0,
                "cwd": row["directory"],
            },
            ensure_ascii=False,
        )

        records.append(
            TokenRecord(
                timestamp=ts,
                agent=agent_name,
                model=model,
                session_id=row["session_id"] or "",
                project=project_from_cwd(row["directory"]),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                reasoning_tokens=row["reasoning_tokens"] or 0,
                cost_usd=round(cost, 6),
                raw_data=raw,
            )
        )
        max_completed_ms = max(max_completed_ms, row["completed_at"])

    logger.info("ZCode: extracted %d records from database", len(records))
    return records, max_completed_ms


def _source_signature(db_path: Path) -> tuple | None:
    """Cheap change-detection signature: (mtime, size) of db and its WAL.

    WAL-mode writes land in ``-wal`` first, so the main file's mtime alone
    would miss recent writes.  ``-shm`` changes on every reader access and
    is deliberately excluded.
    """
    try:
        main = db_path.stat()
        wal = Path(str(db_path) + "-wal")
        if wal.exists():
            w = wal.stat()
            wal_sig: tuple = (w.st_mtime_ns, w.st_size)
        else:
            wal_sig = (0, 0)
        return (main.st_mtime_ns, main.st_size, wal_sig[0], wal_sig[1])
    except OSError:
        return None


class ZcodeCollector(BaseCollector):
    """Collect token usage from the ZCode CLI usage database."""

    @property
    def name(self) -> str:
        return "zcode"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_completed_ms: int = state.get("last_completed_at_ms", 0)

        src = Path(settings.zcode_db_path)
        if not src.exists():
            logger.debug("ZCode: database not found at %s", src)
            return []

        # Fast-path: skip the copy+query when neither db nor WAL changed.
        sig = await asyncio.to_thread(_source_signature, src)
        if sig is not None and sig == state.get("source_sig"):
            logger.debug("ZCode: source db unchanged, skipping poll")
            return []

        # Snapshot the live db (main + WAL sidecars) before reading.
        tmp_path = await asyncio.to_thread(copy_sqlite_with_wal, src)
        if tmp_path is None:
            logger.warning("ZCode: failed to snapshot %s", src)
            return []

        try:
            records, new_watermark = await asyncio.to_thread(
                extract_model_usage, tmp_path, last_completed_ms, self.name
            )
        finally:
            await asyncio.to_thread(remove_sqlite_temp, tmp_path)

        # Persist watermark even without new records so the fast-path
        # signature stays current.
        self._save_state(
            {
                "last_completed_at_ms": new_watermark,
                "source_sig": sig,
            }
        )

        logger.info("ZCode: collected %d new records", len(records))
        return records
