"""OpenClaude token usage collector.

Reads session JSONL files from the local Windows OpenClaude data directory
(``~/.openclaude/projects/``).  The JSONL format is identical to Claude Code,
so the parsing logic is shared via :mod:`backend.collectors.jsonl_utils`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.jsonl_utils import parse_timestamp, scan_jsonl_directory
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)


class OpenClaudeCollector(BaseCollector):
    """Collect token usage from OpenClaude session JSONL files.

    Zero-intrusion: reads ``~/.openclaude/projects/{project}/{session}.jsonl``
    that OpenClaude writes natively — no hooks, no config needed.

    Incremental collection via file-position watermarks.
    """

    @property
    def name(self) -> str:
        return "openclaude"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")
        last_dt = parse_timestamp(last_ts_str)
        file_positions: dict[str, int] = state.get("file_positions", {})

        projects_dir = Path.home() / ".openclaude" / "projects"
        if not projects_dir.exists():
            logger.debug("OpenClaude: projects dir not found at %s", projects_dir)
            return []

        records, new_positions, max_ts_str = scan_jsonl_directory(
            projects_dir=projects_dir,
            agent_name=self.name,
            last_dt=last_dt,
            file_positions=file_positions,
            include_metadata=True,
        )

        if records:
            self._save_state({
                "last_timestamp": max_ts_str,
                "file_positions": new_positions,
            })

        logger.info("OpenClaude: collected %d new records", len(records))
        return records
