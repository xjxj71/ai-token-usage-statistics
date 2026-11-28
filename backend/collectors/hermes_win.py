"""Windows-native Hermes state.db collector.

Reads ``%LOCALAPPDATA%\\hermes\\state.db`` directly — no WSL copy needed.
Inherits the session-tracking logic (hourly increments for open sessions,
one consolidated row per closed session) from
:class:`backend.collectors.hermes.HermesCollector` by overriding *only* the
data-source acquisition step (:meth:`collect`).

State isolation
---------------
``_load_state`` / ``_save_state`` are keyed by ``self.name``, so
``hermes`` (WSL) and ``hermes-win`` (Windows) maintain completely
independent collector state files.  No cross-contamination.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

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
    * No WSL guard: this collector never touches the distro.
    * Automatically skipped when the Windows Hermes data directory does
      not exist (e.g. running inside WSL where LOCALAPPDATA is unset).
    """

    @property
    def name(self) -> str:
        return "hermes-win"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()

        # Resolve the Windows-local state.db path.
        src_path = settings.hermes_win_db_path
        if not src_path:
            # LOCALAPPDATA not set — not on Windows or unusual environment.
            return []

        # Fast-path: skip if source DB (incl. WAL) has not changed since
        # last poll — the inherited signature covers -wal; main-file mtime
        # alone misses writes between checkpoints.
        src_sig = await asyncio.to_thread(self._source_signature, src_path)
        if src_sig is None:
            logger.debug("Hermes-win: cannot stat source db at %s", src_path)
            return []

        if self._source_unchanged(state, src_sig):
            logger.debug("Hermes-win: source db unchanged (sig=%s), skipping poll", src_sig)
            return []

        # Direct local copy — no WSL intermediary needed.
        # _copy_to_temp handles the main db + WAL/SHM sidecar files.
        tmp_path = await self._copy_to_temp(src_path)
        if tmp_path is None:
            logger.warning("Hermes-win: _copy_to_temp returned None for %s", src_path)
            return []

        logger.info("Hermes-win: temp copy at %s", tmp_path)

        try:
            records, new_state = await self._read_sessions(tmp_path, state)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        self._save_state({**new_state, "source_sig": src_sig})
        self._log_cycle(records, new_state)
        return records
