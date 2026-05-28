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
        last_tokens: dict[str, dict[str, int]] = state.get("last_tokens", {})
        last_seen: dict[str, str] = state.get("last_seen", {})

        # First-run detection: if last_tokens is empty, this is the first
        # poll after a fresh start or state reset.  Do a SEED run that
        # populates snapshots without writing records — prevents dumping
        # all sessions into "today" on startup.
        is_first_run = len(last_tokens) == 0

        logger.info(
            "Hermes: state loaded — closed_up_to=%d, open=%d, finalized=%d, last_tokens=%d, first_run=%s",
            closed_up_to_rowid, len(open_session_ids), len(finalized_ids), len(last_tokens), is_first_run,
        )

        if not finalized_ids and closed_up_to_rowid > 0:
            logger.info("Hermes: migration — resetting watermark to repair stale snapshots")
            closed_up_to_rowid = 0

        if not settings.wsl_copy_to_tmp(
            "/root/.hermes/state.db", "/tmp/hermes_state.db"
        ):
            logger.warning("Hermes: failed to copy state.db via wsl_copy")
            return []

        # Also copy WAL and SHM sidecar files for fresh data
        for suffix in ("-wal", "-shm"):
            settings.wsl_copy_to_tmp(
                f"/root/.hermes/state.db{suffix}", f"/tmp/hermes_state.db{suffix}"
            )

        db_path = settings.hermes_db_path
        if not Path(db_path).exists():
            logger.warning("Hermes: copied file not accessible at %s", db_path)
            return []

        tmp_path = await self._copy_to_temp(db_path)
        if tmp_path is None:
            logger.warning("Hermes: _copy_to_temp returned None for %s", db_path)
            return []

        logger.info("Hermes: temp copy at %s", tmp_path)

        try:
            records, still_open, new_closed_up_to, new_finalized, new_last_tokens, new_last_seen = await self._read_sessions(
                tmp_path, closed_up_to_rowid, open_session_ids, finalized_ids, last_tokens, last_seen,
                seed_mode=is_first_run,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        self._save_state({
            "closed_up_to_rowid": new_closed_up_to,
            "open_session_ids": still_open,
            "finalized_ids": new_finalized,
            "last_tokens": new_last_tokens,
            "last_seen": new_last_seen,
        })

        logger.info(
            "Hermes: collected %d records (open: %d, closed_up_to: %d)",
            len(records), len(still_open), new_closed_up_to,
        )
        return records

    async def _copy_to_temp(self, db_path: str) -> str | None:
        """Copy the UNC-accessible db to a local temp file for SQLite access.

        SQLite WAL mode stores recent writes in a separate ``-wal`` file.
        We must copy both the main db **and** the WAL/SHM sidecar files,
        otherwise the temp copy will be missing the latest data.
        """
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            shutil.copy2(db_path, tmp_path)
            # Copy WAL and SHM sidecar files if they exist
            for suffix in ("-wal", "-shm"):
                src_sidecar = db_path + suffix
                if Path(src_sidecar).exists():
                    shutil.copy2(src_sidecar, tmp_path + suffix)
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
        last_seen: dict[str, str],
        seed_mode: bool = False,
    ) -> tuple[list[TokenRecord], list[str], int, list[str], dict[str, dict[str, int]], dict[str, str]]:
        """Read sessions and produce token records.

        Dual-mode strategy:
        - **Closed sessions** (ended_at IS NOT NULL): inserted once with
          final cumulative values.  Tracked in ``finalized_ids`` to avoid
          redundant re-reads.
        - **Open sessions** (ended_at IS NULL): upserted every poll with
          **cumulative** (not delta) values so that the dashboard always
          shows the correct total when querying "today".

        Staleness filter: open sessions with no token change in >24h
        are skipped to prevent old idle sessions from appearing in
        "today" dashboard.

        Seed mode (first run): only populates last_tokens/last_seen
        snapshots without writing records — prevents dumping all
        sessions into "today" on startup.

        Returns:
            (records, still_open_ids, new_closed_up_to_rowid, finalized_ids, new_last_tokens, new_last_seen)
        """
        records: list[TokenRecord] = []

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row

            # Build query: new sessions (rowid past watermark) OR sessions
            # we're still tracking because they were open last cycle.
            # Exclude finalized sessions ONLY if they are actually closed
            # (ended_at IS NOT NULL).  A session that was once closed but
            # reopened (ended_at reset to NULL) must NOT be excluded.
            conditions = ["rowid > ?"]
            params: list = [closed_up_to_rowid]

            if open_session_ids:
                placeholders = ",".join("?" for _ in open_session_ids)
                conditions.append(f"id IN ({placeholders})")
                params += open_session_ids

            if finalized_ids:
                # Only exclude finalized sessions that are truly closed
                placeholders = ",".join("?" for _ in finalized_ids)
                conditions.append(f"NOT (id IN ({placeholders}) AND ended_at IS NOT NULL)")
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
                return records, open_session_ids, closed_up_to_rowid, finalized_ids, last_tokens, last_seen

            logger.info(
                "Hermes: query returned %d rows (conditions: %s)",
                len(rows), len(conditions),
            )

            still_open: list[str] = []
            max_closed_rowid = closed_up_to_rowid
            new_finalized = list(finalized_ids)
            new_last_tokens = dict(last_tokens)
            new_last_seen = dict(last_seen)

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
                    # Session reopened — remove from finalized so it's
                    # not excluded from future queries
                    if session_id in new_finalized:
                        new_finalized.remove(session_id)

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

                # Track last time tokens actually changed
                if tokens_changed:
                    new_last_seen[session_id] = datetime.now(timezone.utc).isoformat()

                # Seed mode: only populate snapshots, don't write records
                if seed_mode:
                    continue

                # Skip if nothing changed since last poll
                if not tokens_changed:
                    continue

                # Skip stale open sessions: if the last token change was
                # more than 24 hours ago, don't write a record.  This
                # prevents old idle sessions from being attributed to
                # "today" in the dashboard.
                if ended_at is None:
                    last_seen_str = new_last_seen.get(session_id)
                    if last_seen_str:
                        try:
                            last_seen_dt = datetime.fromisoformat(last_seen_str)
                            if datetime.now(timezone.utc) - last_seen_dt > timedelta(hours=24):
                                logger.info(
                                    "Hermes: skipping stale session %s (last seen %s)",
                                    session_id[:20], last_seen_str[:19],
                                )
                                continue
                        except (ValueError, TypeError):
                            pass

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

                # Timestamp: round to the hour (floor) so that each hour
                # gets its own cumulative snapshot.  The upsert key includes
                # timestamp, so same-hour polls update the same record while
                # different hours create new ones — preserving history.
                started_at = row["started_at"]
                now_utc = datetime.now(timezone.utc)
                if ended_at is None:
                    # Open session — round current time to hour
                    hour_ts = now_utc.replace(minute=0, second=0, microsecond=0)
                elif started_at:
                    # Closed session — round creation time to hour
                    hour_ts = datetime.fromtimestamp(started_at, tz=timezone.utc).replace(
                        minute=0, second=0, microsecond=0
                    )
                else:
                    hour_ts = now_utc.replace(minute=0, second=0, microsecond=0)
                ts = hour_ts.isoformat()

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

        logger.info(
            "Hermes: _read_sessions done — %d records, %d still_open, max_closed=%d",
            len(records), len(still_open), max_closed_rowid,
        )
        return records, still_open, max_closed_rowid, new_finalized, new_last_tokens, new_last_seen
