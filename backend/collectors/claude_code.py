from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.config import settings
from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string, falling back to epoch on failure."""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


class ClaudeCodeCollector(BaseCollector):
    """Collect token usage from Claude Code session JSONL files.

    Zero-intrusion: reads ~/.claude/projects/{project}/{session}.jsonl
    that Claude Code writes natively — no hooks, no config needed.
    """

    @property
    def name(self) -> str:
        return "claude-code"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")
        last_dt = _parse_ts(last_ts_str)
        # Track processed file positions for incremental reads
        file_positions: dict[str, int] = state.get("file_positions", {})

        # Fix permissions on root-owned files before scanning
        settings.ensure_claude_projects_readable()

        projects_dir = Path(settings.claude_projects_dir)
        if not projects_dir.exists():
            logger.debug("Claude Code: projects dir not found at %s", projects_dir)
            return []

        records: list[TokenRecord] = []
        max_ts_str = last_ts_str
        new_positions: dict[str, int] = {}

        # Walk all .jsonl files under projects/ (including subagents/)
        jsonl_files = sorted(projects_dir.rglob("*.jsonl"))
        logger.debug("Claude Code: scanning %d jsonl files", len(jsonl_files))

        for fpath in jsonl_files:
            # Use relative path as key for position tracking
            rel_key = str(fpath.relative_to(projects_dir))
            start_pos = file_positions.get(rel_key, 0)

            try:
                file_size = fpath.stat().st_size
            except OSError:
                continue

            # File was truncated or replaced — reset position
            if start_pos > file_size:
                start_pos = 0

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    if start_pos > 0:
                        f.seek(start_pos)

                    for line_no, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue

                        # Quick filter: skip non-assistant lines early
                        if '"type":"assistant"' not in line and '"type": "assistant"' not in line:
                            continue
                        # Quick filter: must have usage data
                        if "input_tokens" not in line:
                            continue

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if data.get("type") != "assistant":
                            continue

                        usage = data.get("message", {}).get("usage", {})
                        if not usage:
                            continue

                        # Extract fields
                        ts = data.get("timestamp", "")
                        ts_dt = _parse_ts(ts)
                        if ts_dt <= last_dt:
                            continue

                        model = data.get("message", {}).get("model", "unknown")
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        cache_read = usage.get("cache_read_input_tokens", 0)
                        cache_write = usage.get("cache_creation_input_tokens", 0)

                        # Skip all-zero records (some early sessions had these)
                        if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
                            continue

                        cost = calculate_cost(
                            model, input_tokens, output_tokens, cache_read, cache_write
                        )

                        # Build enriched raw_data with metadata
                        meta = {
                            "uuid": data.get("uuid", ""),
                            "sessionId": data.get("sessionId", ""),
                            "cwd": data.get("cwd", ""),
                            "gitBranch": data.get("gitBranch", ""),
                            "version": data.get("version", ""),
                            "entrypoint": data.get("entrypoint", ""),
                            "isSidechain": data.get("isSidechain", False),
                            "agentId": data.get("agentId", ""),
                            "slug": data.get("slug", ""),
                        }

                        records.append(
                            TokenRecord(
                                timestamp=ts,
                                agent=self.name,
                                model=model,
                                session_id=data.get("sessionId", ""),
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cache_read_tokens=cache_read,
                                cache_write_tokens=cache_write,
                                cost_usd=round(cost, 6),
                                raw_data=json.dumps(meta, ensure_ascii=False),
                            )
                        )
                        if ts_dt > _parse_ts(max_ts_str):
                            max_ts_str = ts

                    # Record current position for incremental reads
                    new_positions[rel_key] = f.tell()

            except OSError as e:
                logger.warning("Claude Code: failed to read %s: %s", fpath, e)
                continue

        if records:
            self._save_state({
                "last_timestamp": max_ts_str,
                "file_positions": new_positions,
            })

        logger.info("Claude Code: collected %d new records", len(records))
        return records
