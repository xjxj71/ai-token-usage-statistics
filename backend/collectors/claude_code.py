"""Claude Code token usage collector.

Reads session JSONL files from ~/.claude/projects/ via WSL UNC paths.
Zero-intrusion: Claude Code writes session files natively — no hooks or config needed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from backend.collectors.base import BaseCollector
from backend.collectors.jsonl_utils import parse_timestamp, scan_jsonl_directory
from backend.config import settings
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)


class ClaudeCodeCollector(BaseCollector):
    """Collect token usage from Claude Code session JSONL files."""

    @property
    def name(self) -> str:
        return "claude-code"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")
        last_dt = parse_timestamp(last_ts_str)
        file_positions: dict[str, int] = state.get("file_positions", {})

        # Fix permissions on root-owned files before scanning
        settings.ensure_claude_projects_readable()

        projects_dir = Path(settings.claude_projects_dir)
        if not projects_dir.exists():
            logger.debug("Claude Code: projects dir not found at %s", projects_dir)
            return []

        records, new_positions, max_ts_str = scan_jsonl_directory(
            projects_dir=projects_dir,
            agent_name=self.name,
            last_dt=last_dt,
            file_positions=file_positions,
            include_metadata=True,
        )

        # Always persist position watermarks even if no new records were
        # produced. Otherwise a truncated/replaced file with start_pos=0
        # would lose its reset on the next poll and re-read the same
        # content on every cycle.
        self._save_state(
            {
                "last_timestamp": max_ts_str or last_ts_str,
                "file_positions": new_positions,
            }
        )

        logger.info("Claude Code: collected %d new records", len(records))
        return records
