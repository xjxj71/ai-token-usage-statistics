"""OpenClaude token usage collector.

Reads session JSONL files from the local Windows OpenClaude data directory
(``~/.openclaude/projects/``).  The JSONL format is identical to Claude Code,
so the parsing logic is shared via :mod:`backend.collectors.jsonl_utils`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

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
        return "openclaw"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")

        projects_dir = Path.home() / ".openclaw" / "projects"
        if not projects_dir.exists():
            logger.debug("OpenClaude: projects dir not found at %s", projects_dir)
            return []

        # Discover current files first so we can prune deleted-file positions.
        existing_keys: set[str] = set()
        for fpath in projects_dir.rglob("*.jsonl"):
            try:
                existing_keys.add(str(fpath.relative_to(projects_dir)))
            except OSError:
                continue

        file_positions: dict[str, int] = state.get("file_positions", {})

        # Deserialise state schema validation: file_positions values must be ints.
        validated_positions: dict[str, int] = {}
        for key, pos in file_positions.items():
            try:
                validated_positions[key] = int(pos)
            except (TypeError, ValueError):
                logger.debug("OpenClaude: dropping bad file_position for %r", key)

        records, new_positions, max_ts_str = scan_jsonl_directory(
            projects_dir=projects_dir,
            agent_name=self.name,
            last_dt=parse_timestamp(last_ts_str),
            file_positions=validated_positions,
            include_metadata=True,
        )

        # Prune positions for deleted files before persisting.
        pruned_positions = {k: v for k, v in new_positions.items() if k in existing_keys}
        if pruned_positions != new_positions:
            logger.debug(
                "OpenClaude: dropped %d stale file position(s)",
                len(new_positions) - len(pruned_positions),
            )

        # Always persist position watermarks even without new records:
        # this preserves file truncation resets and prevents re-scanning
        # already-consumed files.
        self._save_state(
            {
                "last_timestamp": max_ts_str or last_ts_str,
                "file_positions": pruned_positions,
            }
        )

        logger.info("OpenClaude: collected %d new records", len(records))
        return records
