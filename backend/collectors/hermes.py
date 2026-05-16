from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import aiosqlite

from backend.collectors.base import BaseCollector
from backend.config import settings
from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


class HermesCollector(BaseCollector):
    """Collect token usage from Hermes state.db (sessions table).

    Dual-mode collection:
    - **Closed sessions** (ended_at IS NOT NULL): inserted once with final
      token values, then the rowid watermark advances past them.
    - **Open sessions** (ended_at IS NULL): upserted every poll cycle with
      the latest cumulative token counts.  Tracked in open_session_ids
      until they close.

    On first run after migration from the old `last_row_id` state format,
    ``closed_up_to_rowid`` defaults to 0 which triggers a full re-read of
    all sessions — this automatically fixes any stale snapshot data that
    the previous collector left behind.
    """

    upsert_mode = True

    @property
    def name(self) -> str:
        return "hermes"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        # Migration: old state key was "last_row_id".  If the new key is
        # missing we default to 0, forcing a full re-read that repairs all
        # stale snapshots from the old collector.
        closed_up_to_rowid: int = state.get("closed_up_to_rowid", 0)
        open_session_ids: list[str] = state.get("open_session_ids", [])
        # Sessions confirmed as closed with final data collected.
        # These will not be re-queried even if their rowid is below the watermark.
        finalized_ids: list[str] = state.get("finalized_ids", [])

        # Migration: if finalized_ids is missing but closed_up_to_rowid > 0,
        # we need a repair pass to fix stale snapshots from the old collector.
        # Reset watermark to 0 to re-read all sessions and build finalized_ids.
        if not finalized_ids and closed_up_to_rowid > 0:
            logger.info("Hermes: migration — resetting watermark to repair stale snapshots")
            closed_up_to_rowid = 0

        # Copy state.db from WSL /root to /tmp for UNC access
        if not settings.wsl_copy_to_tmp(
            "/root/.hermes/state.db", "/tmp/hermes_state.db"
        ):
            logger.warning("Hermes: failed to copy state.db via wsl_copy")
            return []

        db_path = settings.hermes_db_path
        if not Path(db_path).exists():
            logger.warning("Hermes: copied file not accessible at %s", db_path)
            return []

        tmp_path = await self._copy_to_temp(db_path)
        if tmp_path is None:
            return []

        try:
            records, still_open, new_closed_up_to, new_finalized = await self._read_sessions(
                tmp_path, closed_up_to_rowid, open_session_ids, finalized_ids
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Always persist state so open_session_ids stays current even when
        # no TokenRecords are produced (e.g. all-zero open sessions).
        self._save_state({
            "closed_up_to_rowid": new_closed_up_to,
            "open_session_ids": still_open,
            "finalized_ids": new_finalized,
        })

        logger.info(
            "Hermes: collected %d records (open: %d, closed_up_to: %d)",
            len(records), len(still_open), new_closed_up_to,
        )
        return records

    async def _copy_to_temp(self, db_path: str) -> str | None:
        """Copy the UNC-accessible db to a local temp file for SQLite access."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            shutil.copy2(db_path, tmp.name)
            return tmp.name
        except OSError as e:
            logger.warning("Failed to copy hermes state.db: %s", e)
            return None

    async def _read_sessions(
        self,
        db_path: str,
        closed_up_to_rowid: int,
        open_session_ids: list[str],
        finalized_ids: list[str],
    ) -> tuple[list[TokenRecord], list[str], int, list[str]]:
        """Read sessions that are new or still open.

        Returns:
            (records, still_open_ids, new_closed_up_to_rowid, finalized_ids)
        """
        records: list[TokenRecord] = []

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row

            # Build query: new sessions (rowid past watermark) OR sessions
            # we're still tracking because they were open last cycle.
            # Exclude finalized closed sessions to avoid redundant re-reads.
            conditions = ["rowid > ?"]
            params: list = [closed_up_to_rowid]

            if open_session_ids:
                placeholders = ",".join("?" for _ in open_session_ids)
                conditions.append(f"id IN ({placeholders})")
                params += open_session_ids

            if finalized_ids:
                placeholders = ",".join("?" for _ in finalized_ids)
                conditions.append(f"id NOT IN ({placeholders})")
                params += finalized_ids

            query = f"""
                SELECT rowid, input_tokens, output_tokens,
                       cache_read_tokens, cache_write_tokens,
                       estimated_cost_usd, actual_cost_usd,
                       started_at, ended_at, model, id
                FROM sessions
                WHERE {" OR ".join(conditions)}
                ORDER BY rowid
            """

            try:
                rows = await db.execute_fetchall(query, params)
            except aiosqlite.OperationalError as e:
                logger.warning("Hermes DB query failed: %s", e)
                return records, open_session_ids, closed_up_to_rowid, finalized_ids

            still_open: list[str] = []
            max_closed_rowid = closed_up_to_rowid
            new_finalized = list(finalized_ids)

            for row in rows:
                row_id = row["rowid"]
                session_id = str(row["id"] or "")
                ended_at = row["ended_at"]
                model = row["model"] or "unknown"
                input_tokens = row["input_tokens"] or 0
                output_tokens = row["output_tokens"] or 0
                cache_read = row["cache_read_tokens"] or 0
                cache_write = row["cache_write_tokens"] or 0

                # Track session lifecycle
                if ended_at is not None:
                    # Closed — advance watermark past it and mark finalized
                    if row_id > max_closed_rowid:
                        max_closed_rowid = row_id
                    if session_id not in new_finalized:
                        new_finalized.append(session_id)
                else:
                    # Still in progress — keep tracking next cycle
                    still_open.append(session_id)

                # Skip all-zero records (empty / aborted sessions)
                if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
                    continue

                # Cost: prefer actual_cost if available, else calculate
                actual_cost = row["actual_cost_usd"]
                cost = (
                    actual_cost
                    if actual_cost and actual_cost > 0
                    else calculate_cost(
                        model, input_tokens, output_tokens, cache_read, cache_write
                    )
                )

                # started_at is REAL (Unix timestamp), convert to ISO string
                started_at = row["started_at"]
                if started_at:
                    ts = datetime.fromtimestamp(
                        started_at, tz=timezone.utc
                    ).isoformat()
                else:
                    ts = datetime.now(timezone.utc).isoformat()

                records.append(
                    TokenRecord(
                        timestamp=ts,
                        agent=self.name,
                        model=model,
                        session_id=session_id,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                        cost_usd=round(cost, 6),
                        raw_data=json.dumps(
                            {
                                "_row_id": row_id,
                                "ended": ended_at is not None,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )

        return records, still_open, max_closed_rowid, new_finalized
