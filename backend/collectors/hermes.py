from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
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

    Dual-mode lifecycle:
    - **Closed sessions** (ended_at IS NOT NULL): inserted once with final
      cumulative token values.  Tracked in ``finalized_ids`` to avoid
      redundant re-reads.
    - **Open sessions** (ended_at IS NULL): upserted every poll with
      **cumulative** (not delta) values so the dashboard always shows the
      correct total for "today" queries.  Each poll replaces the previous
      cumulative snapshot via upsert on (timestamp, agent, session_id, model).

    ``last_tokens`` is a dict keyed by session_id capturing the most recent
    token snapshot, used only to detect *whether* tokens changed (skip
    redundant writes when nothing moved).
    """

    upsert_mode = True

    @property
    def name(self) -> str:
        return "hermes"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        closed_up_to_rowid: int = state.get("closed_up_to_rowid", 0)
        open_session_ids: list[str] = state.get("open_session_ids", [])
        finalized_ids: list[str] = state.get("finalized_ids", [])
        # Last-known token snapshots for delta calculation
        last_tokens: dict[str, dict[str, int]] = state.get("last_tokens", {})

        if not finalized_ids and closed_up_to_rowid > 0:
            logger.info("Hermes: migration — resetting watermark to repair stale snapshots")
            closed_up_to_rowid = 0

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
            records, still_open, new_closed_up_to, new_finalized, new_last_tokens = await self._read_sessions(
                tmp_path, closed_up_to_rowid, open_session_ids, finalized_ids, last_tokens,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        self._save_state({
            "closed_up_to_rowid": new_closed_up_to,
            "open_session_ids": still_open,
            "finalized_ids": new_finalized,
            "last_tokens": new_last_tokens,
        })

        logger.info(
            "Hermes: collected %d records (open: %d, closed_up_to: %d)",
            len(records), len(still_open), new_closed_up_to,
        )
        return records

    async def _copy_to_temp(self, db_path: str) -> str | None:
        """Copy the UNC-accessible db to a local temp file for SQLite access."""
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            shutil.copy2(db_path, tmp_path)
            return tmp_path
        except OSError as e:
            logger.warning("Failed to copy hermes state.db: %s", e)
            return None

    async def _read_sessions(
        self,
        db_path: str,
        closed_up_to_rowid: int,
        open_session_ids: list[str],
        finalized_ids: list[str],
        last_tokens: dict[str, dict[str, int]],
    ) -> tuple[list[TokenRecord], list[str], int, list[str], dict[str, dict[str, int]]]:
        """Read sessions and produce token records.

        Dual-mode strategy:
        - **Closed sessions** (ended_at IS NOT NULL): inserted once with
          final cumulative values.  Tracked in ``finalized_ids`` to avoid
          redundant re-reads.
        - **Open sessions** (ended_at IS NULL): upserted every poll with
          **cumulative** (not delta) values so that the dashboard always
          shows the correct total when querying "today".

        Returns:
            (records, still_open_ids, new_closed_up_to_rowid, finalized_ids, new_last_tokens)
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
                return records, open_session_ids, closed_up_to_rowid, finalized_ids, last_tokens

            still_open: list[str] = []
            max_closed_rowid = closed_up_to_rowid
            new_finalized = list(finalized_ids)
            new_last_tokens = dict(last_tokens)

            for row in rows:
                row_id = row["rowid"]
                session_id = str(row["id"] or "")
                ended_at = row["ended_at"]
                model = row["model"] or "unknown"

                # Track session lifecycle
                if ended_at is not None:
                    if row_id > max_closed_rowid:
                        max_closed_rowid = row_id
                    if session_id not in new_finalized:
                        new_finalized.append(session_id)
                else:
                    still_open.append(session_id)

                # Current cumulative values from state.db
                cur_input = row["input_tokens"] or 0
                cur_output = row["output_tokens"] or 0
                cur_cr = row["cache_read_tokens"] or 0
                cur_cw = row["cache_write_tokens"] or 0

                # Detect whether tokens changed since last poll
                prev = new_last_tokens.get(session_id, {})
                tokens_changed = (
                    cur_input != prev.get("input", 0)
                    or cur_output != prev.get("output", 0)
                    or cur_cr != prev.get("cache_read", 0)
                    or cur_cw != prev.get("cache_write", 0)
                )

                # Update snapshot
                new_last_tokens[session_id] = {
                    "input": cur_input,
                    "output": cur_output,
                    "cache_read": cur_cr,
                    "cache_write": cur_cw,
                }

                # Skip if nothing changed since last poll
                if not tokens_changed:
                    continue

                # Cost: prefer actual_cost if available, else calculate
                # from cumulative values
                actual_cost = row["actual_cost_usd"]
                cost = (
                    actual_cost
                    if actual_cost and actual_cost > 0
                    else calculate_cost(
                        model, cur_input, cur_output, cur_cr, cur_cw
                    )
                )

                # Timestamp: closed sessions use started_at (fixed), open
                # sessions use today's date so cumulative values appear in
                # the correct "today" range when queried by the dashboard.
                started_at = row["started_at"]
                if ended_at is not None:
                    # Closed — stable timestamp
                    if started_at:
                        ts = datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat()
                    else:
                        ts = datetime.now(timezone.utc).isoformat()
                else:
                    # Open — use Beijing midnight (converted to UTC) so the
                    # record falls within the dashboard's "today" query range,
                    # which also uses Beijing midnight → UTC conversion.
                    import zoneinfo
                    try:
                        local_tz = zoneinfo.ZoneInfo("Asia/Shanghai")
                    except Exception:
                        local_tz = timezone(timedelta(hours=8))
                    now_local = datetime.now(local_tz)
                    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_start_utc = today_start_local.astimezone(timezone.utc)
                    ts = today_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

                records.append(
                    TokenRecord(
                        timestamp=ts,
                        agent=self.name,
                        model=model,
                        session_id=session_id,
                        input_tokens=cur_input,
                        output_tokens=cur_output,
                        cache_read_tokens=cur_cr,
                        cache_write_tokens=cur_cw,
                        cost_usd=round(cost, 6),
                        raw_data=json.dumps(
                            {
                                "_row_id": row_id,
                                "ended": ended_at is not None,
                                "last_seen": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )

        return records, still_open, max_closed_rowid, new_finalized, new_last_tokens
