"""MimoCode token usage collector.

Reads token usage from MiMoCode's SQLite database at ~/.local/share/mimocode/mimocode.db.
MiMoCode is a fork of OpenCode, so it shares the same database schema.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.opencode_db_utils import extract_token_records
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)

# Default database path for MiMoCode
_MIMOCODE_DB_PATH = Path.home() / ".local" / "share" / "mimocode" / "mimocode.db"


class MimoCodeCollector(BaseCollector):
    """Collect token usage from MiMoCode SQLite database."""

    @property
    def name(self) -> str:
        return "mimo-code"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_ms = state.get("last_timestamp_ms", 0)

        records, new_max_ts = extract_token_records(
            db_path=_MIMOCODE_DB_PATH,
            agent_name=self.name,
            last_timestamp_ms=last_ts_ms,
        )

        # Persist watermark
        self._save_state({"last_timestamp_ms": new_max_ts})

        logger.info("MimoCode: collected %d new records", len(records))
        return records
