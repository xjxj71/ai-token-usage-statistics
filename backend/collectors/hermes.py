from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from backend.collectors.base import BaseCollector
from backend.collectors.sqlite_utils import copy_sqlite_with_wal
from backend.config import settings
from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


class HermesCollector(BaseCollector):
    """Collect token usage from Hermes state.db (sessions table).

    Hermes keeps **cumulative per-session counters**.  Every row this
    collector writes is nevertheless a true increment, so the rest of the
    app can SUM rows for Hermes exactly like it does for every other agent
    (summing cumulative snapshots used to count a session's tokens once per
    hour it stayed open — 3.4x on real data).

    - **Open session** — one row per (session, hour) holding that hour's
      usage.  The rows are re-derived on every poll from ``session_marks``
      (the counters at the start of each hour), so a repeated poll upserts
      the same absolute values rather than adding to them: a lost or corrupt
      state file can never double count.
    - **Closed session** — the session's rows are replaced by a single row
      with the final totals taken straight from state.db, which also heals
      whatever the hourly rows looked like.

    ``last_tokens`` only tells *whether* a session's counters moved;
    unchanged sessions are skipped.
    """

    upsert_mode = True

    @property
    def name(self) -> str:
        return "hermes"

    async def collect(self) -> Sequence[TokenRecord]:
        # WSL guard: bail before touching the distro — the source stat on
        # the UNC path, the wsl.exe copies, and the snapshot read would
        # all boot a stopped WSL.
        if not await asyncio.to_thread(settings.is_wsl_running):
            logger.debug(
                "Hermes: WSL distro '%s' not running, skipping poll",
                settings.wsl_distro,
            )
            return []

        state = self._load_state()

        # Fast-path: skip if source DB did not change since last poll.
        # Use the platform-appropriate path for stat: UNC on Windows,
        # native Linux path inside WSL.
        if settings.is_wsl:
            src_path = "/root/.hermes/state.db"
        else:
            src_path = f"{settings.wsl_root}\\root\\.hermes\\state.db"

        # Stat may fail if WSL distro is stopped or not installed — don't
        # bail out, fall through to wsl_copy_to_tmp which may still succeed.
        src_sig = await asyncio.to_thread(self._source_signature, src_path)

        if self._source_unchanged(state, src_sig):
            logger.debug("Hermes: source db unchanged (sig=%s), skipping poll", src_sig)
            return []

        if not await asyncio.to_thread(
            settings.wsl_copy_to_tmp, "/root/.hermes/state.db", "/tmp/hermes_state.db"
        ):
            logger.warning("Hermes: failed to copy state.db via wsl_copy")
            return []

        # Also copy WAL and SHM sidecar files for fresh data
        for suffix in ("-wal", "-shm"):
            await asyncio.to_thread(
                settings.wsl_copy_to_tmp,
                f"/root/.hermes/state.db{suffix}",
                f"/tmp/hermes_state.db{suffix}",
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
            records, new_state = await self._read_sessions(tmp_path, state)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Fresh signature for next poll's fast-path; if the source stat
        # failed (WSL down), sign the copied file instead.
        stat_target = src_path if src_sig is not None else db_path
        fresh_sig = await asyncio.to_thread(self._source_signature, stat_target)

        self._save_state({**new_state, "source_sig": fresh_sig})
        self._log_cycle(records, new_state)
        return records

    @staticmethod
    def _source_signature(src_path: str) -> tuple | None:
        """Cheap change-detection signature: (mtime_ns, size) of db and WAL.

        WAL-mode writes land in ``-wal`` first, so the main file's mtime
        alone misses every write between checkpoints (same rationale as
        ``zcode._source_signature``).  ``-shm`` changes on every reader
        access and is deliberately excluded.
        """
        try:
            main = Path(src_path).stat()
            wal = Path(src_path + "-wal")
            if wal.exists():
                w = wal.stat()
                wal_sig = (w.st_mtime_ns, w.st_size)
            else:
                wal_sig = (0, 0)
            return (main.st_mtime_ns, main.st_size, *wal_sig)
        except OSError as exc:
            logger.debug("Hermes: cannot stat source db at %s: %s", src_path, exc)
            return None

    @staticmethod
    def _source_unchanged(state: dict, sig: tuple | None) -> bool:
        prev = state.get("source_sig")
        # JSON round-trips tuples as lists; older state (source_mtime/size
        # only) has no source_sig → one full poll re-establishes it.
        return sig is not None and prev is not None and tuple(prev) == sig

    def _log_cycle(self, records: list[TokenRecord], state: dict) -> None:
        logger.info(
            "%s: collected %d records (open: %d, closed_up_to: %d)",
            self.name, len(records), len(state.get("open_session_ids", [])),
            state.get("closed_up_to_rowid", 0),
        )

    async def _copy_to_temp(self, db_path: str) -> str | None:
        """Copy the source db (plus WAL/SHM sidecars) to a temp snapshot.

        The blocking copy runs in a worker thread — reading from a UNC path
        can take seconds and must not stall the event loop.
        """
        return await asyncio.to_thread(copy_sqlite_with_wal, db_path)

    async def _read_sessions(
        self, db_path: str, state: dict
    ) -> tuple[list[TokenRecord], dict]:
        """Read sessions past the watermark and turn their counters into
        increment records.

        Returns ``(records, new_state)``.  A failed query hands the input
        state back untouched so the watermark does not move past rows that
        were never read.
        """
        records: list[TokenRecord] = []
        closed_up_to_rowid: int = state.get("closed_up_to_rowid", 0)
        open_session_ids: list[str] = state.get("open_session_ids", [])
        finalized_ids: list[str] = state.get("finalized_ids", [])
        last_tokens: dict[str, dict[str, int]] = state.get("last_tokens", {})
        session_marks: dict[str, dict] = state.get("session_marks", {})
        last_poll_at: str | None = state.get("last_poll_at")

        now_utc = datetime.now(UTC)
        hour_now = now_utc.replace(minute=0, second=0, microsecond=0).isoformat()
        last_poll_ts: float | None = None
        if last_poll_at:
            try:
                last_poll_ts = datetime.fromisoformat(last_poll_at).timestamp()
            except ValueError:
                last_poll_ts = None

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row

            # New sessions (rowid past the watermark) OR sessions still
            # tracked because they were open last cycle.  Finalized sessions
            # are excluded only while they are really closed — one that was
            # closed and then reopened (ended_at back to NULL) must show up
            # again.
            conditions = ["rowid > ?"]
            params: list = [closed_up_to_rowid]

            if open_session_ids:
                placeholders = ",".join("?" for _ in open_session_ids)
                conditions.append(f"id IN ({placeholders})")
                params += open_session_ids

            if finalized_ids:
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
            except sqlite3.Error as e:
                logger.warning("Hermes DB query failed: %s", e)
                return records, state

            logger.info(
                "Hermes: query returned %d rows (conditions: %s)",
                len(rows), len(conditions),
            )

            still_open: list[str] = []
            max_closed_rowid = closed_up_to_rowid
            new_finalized = list(finalized_ids)
            new_last_tokens = dict(last_tokens)
            new_marks = dict(session_marks)

            for row in rows:
                row_id = row["rowid"]
                session_id = str(row["id"] or "")
                ended_at = row["ended_at"]
                started_at = row["started_at"]
                model = row["model"] or "unknown"

                # Track session lifecycle
                if ended_at is not None:
                    max_closed_rowid = max(max_closed_rowid, row_id)
                    if session_id not in new_finalized:
                        new_finalized.append(session_id)
                else:
                    still_open.append(session_id)
                    # Session reopened — remove from finalized so it's
                    # not excluded from future queries
                    if session_id in new_finalized:
                        new_finalized.remove(session_id)

                # Cumulative counters so far in this session
                cur = (
                    row["input_tokens"] or 0,
                    row["output_tokens"] or 0,
                    row["cache_read_tokens"] or 0,
                    row["cache_write_tokens"] or 0,
                )

                prev = new_last_tokens.get(session_id, {})
                tokens_changed = (
                    cur[0] != prev.get("input", 0)
                    or cur[1] != prev.get("output", 0)
                    or cur[2] != prev.get("cache_read", 0)
                    or cur[3] != prev.get("cache_write", 0)
                )
                new_last_tokens[session_id] = {
                    "input": cur[0],
                    "output": cur[1],
                    "cache_read": cur[2],
                    "cache_write": cur[3],
                }
                if not tokens_changed:
                    continue

                # Cost: prefer actual_cost if available, else calculate
                # from the cumulative values
                actual_cost = row["actual_cost_usd"]
                cum_cost = (
                    actual_cost
                    if actual_cost and actual_cost > 0
                    else calculate_cost(model, *cur)
                )
                seen_at = now_utc.isoformat()

                if ended_at is not None:
                    # Closed: one row with the session's final totals replaces
                    # every hourly row the open phase left behind.
                    new_marks.pop(session_id, None)
                    started = (
                        datetime.fromtimestamp(started_at, tz=UTC) if started_at else now_utc
                    )
                    ts = started.replace(minute=0, second=0, microsecond=0).isoformat()
                    records.append(
                        TokenRecord(
                            timestamp=ts,
                            agent=self.name,
                            model=model,
                            session_id=session_id,
                            input_tokens=cur[0],
                            output_tokens=cur[1],
                            cache_read_tokens=cur[2],
                            cache_write_tokens=cur[3],
                            cost_usd=round(cum_cost, 6),
                            replace_session=True,
                            raw_data=json.dumps(
                                {"_row_id": row_id, "ended": True, "last_seen": seen_at},
                                ensure_ascii=False,
                            ),
                        )
                    )
                    continue

                # Open: one row per hour holding that hour's usage.  ``hours``
                # keeps the counters at the start of each hour, so a row is
                # always (next start − this start) and re-polling rewrites the
                # same absolute values.
                mark = new_marks.get(session_id)
                if mark is None:
                    # First sight of this session.  One created since the
                    # previous poll starts from zero; anything older may
                    # carry usage from before we watched it, so its current
                    # counters become the baseline.
                    is_new = (
                        last_poll_ts is not None
                        and bool(started_at)
                        and started_at > last_poll_ts
                    )
                    base = [0, 0, 0, 0, 0.0] if is_new else [*cur, cum_cost]
                    mark = {"hours": [[hour_now, *base]], "last": [*cur, cum_cost]}
                    new_marks[session_id] = mark
                if mark["hours"][-1][0] != hour_now:
                    mark["hours"].append([hour_now, *mark["last"]])
                mark["last"] = [*cur, cum_cost]

                hours = mark["hours"]
                for i, start in enumerate(hours):
                    end = hours[i + 1][1:] if i + 1 < len(hours) else mark["last"]
                    delta = [max(e - s, 0) for s, e in zip(start[1:], end)]
                    if not any(delta):
                        continue
                    records.append(
                        TokenRecord(
                            timestamp=start[0],
                            agent=self.name,
                            model=model,
                            session_id=session_id,
                            input_tokens=int(delta[0]),
                            output_tokens=int(delta[1]),
                            cache_read_tokens=int(delta[2]),
                            cache_write_tokens=int(delta[3]),
                            cost_usd=round(delta[4], 6),
                            raw_data=json.dumps(
                                {
                                    "_row_id": row_id,
                                    "ended": False,
                                    "mode": "delta",
                                    "last_seen": seen_at,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )

        # Marks only matter while a session is open.
        open_set = set(still_open)
        new_marks = {sid: m for sid, m in new_marks.items() if sid in open_set}

        new_state = {
            "closed_up_to_rowid": max_closed_rowid,
            "open_session_ids": still_open,
            "finalized_ids": new_finalized,
            "last_tokens": new_last_tokens,
            "session_marks": new_marks,
            "last_poll_at": now_utc.isoformat(),
        }
        logger.info(
            "Hermes: _read_sessions done — %d records, %d still_open, max_closed=%d",
            len(records), len(still_open), max_closed_rowid,
        )
        return records, new_state
