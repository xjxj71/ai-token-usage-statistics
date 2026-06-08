"""Windows-native Hermes state.db collector.

Reads ``%LOCALAPPDATA%\\hermes\\state.db`` directly — no WSL copy needed.
Inherits the full session-tracking, dual-mode, staleness-filter logic from
:class:`HermesCollector` by overriding *only* the data-source acquisition
step (:meth:`collect`).

State isolation
---------------
``_load_state`` / ``_save_state`` are keyed by ``self.name``, so
``hermes`` (WSL) and ``hermes-win`` (Windows) maintain completely
independent collector state files.  No cross-contamination.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.collectors.hermes import HermesCollector
from backend.config import settings
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)


class HermesWindowsCollector(HermesCollector):
    """Collect token usage from the **Windows-native** Hermes state.db.

    Differences from the WSL parent (:class:`HermesCollector`):

    * ``name`` is ``"hermes-win"`` — appears as a distinct agent in the
      dashboard and API.
    * Source path is ``%LOCALAPPDATA%\\hermes\\state.db`` accessed
      directly via ``_copy_to_temp`` — no ``wsl_copy_to_tmp`` step.
    * Fast-path mtime/size check is reused, but against the local file.
    * Automatically skipped when the Windows Hermes data directory does
      not exist (e.g. running inside WSL where LOCALAPPDATA is unset).
    """

    @property
    def name(self) -> str:
        return "hermes-win"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        closed_up_to_rowid: int = state.get("closed_up_to_rowid", 0)
        open_session_ids: list[str] = state.get("open_session_ids", [])
        finalized_ids: list[str] = state.get("finalized_ids", [])
        last_tokens: dict[str, dict[str, int]] = state.get("last_tokens", {})
        last_seen: dict[str, str] = state.get("last_seen", {})

        # Resolve the Windows-local state.db path.
        src_path = settings.hermes_win_db_path
        if not src_path:
            # LOCALAPPDATA not set — not on Windows or unusual environment.
            return []

        # Fast-path: skip if source DB has not changed since last poll.
        try:
            src_stat = Path(src_path).stat()
        except OSError as exc:
            logger.debug(
                "Hermes-win: cannot stat source db at %s: %s", src_path, exc
            )
            return []

        prev_mtime = state.get("source_mtime")
        prev_size = state.get("source_size")
        if (
            prev_mtime is not None
            and prev_size is not None
            and src_stat.st_mtime == prev_mtime
            and src_stat.st_size == prev_size
        ):
            logger.debug(
                "Hermes-win: source db unchanged (mtime=%s), skipping poll",
                src_stat.st_mtime,
            )
            return []

        # Direct local copy — no WSL intermediary needed.
        # _copy_to_temp handles the main db + WAL/SHM sidecar files.
        tmp_path = await self._copy_to_temp(src_path)
        if tmp_path is None:
            logger.warning("Hermes-win: _copy_to_temp returned None for %s", src_path)
            return []

        logger.info("Hermes-win: temp copy at %s", tmp_path)

        try:
            (
                records,
                still_open,
                new_closed_up_to,
                new_finalized,
                new_last_tokens,
                new_last_seen,
            ) = await self._read_sessions(
                tmp_path,
                closed_up_to_rowid,
                open_session_ids,
                finalized_ids,
                last_tokens,
                last_seen,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        self._save_state(
            {
                "closed_up_to_rowid": new_closed_up_to,
                "open_session_ids": still_open,
                "finalized_ids": new_finalized,
                "last_tokens": new_last_tokens,
                "last_seen": new_last_seen,
                "source_mtime": src_stat.st_mtime,
                "source_size": src_stat.st_size,
            }
        )

        logger.info(
            "Hermes-win: collected %d records (open: %d, closed_up_to: %d)",
            len(records),
            len(still_open),
            new_closed_up_to,
        )
        return records
