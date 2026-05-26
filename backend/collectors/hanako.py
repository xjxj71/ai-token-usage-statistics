"""Hanako token usage collector.

Zero-intrusion monitor: reads the *session* JSONL files that Hanako writes
natively to its user data directory (``~/.hanako/agents/hanako/sessions/``).

Why sessions and not activity?
  Activity files are periodic 2-hour snapshots that may miss data during a
  long-running session.  Session files contain the *complete* transcript with
  every API call — the same JSONL schema, just the full story.

No hooks, no config changes, no agent modifications needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.jsonl_utils import parse_timestamp
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)

# Subdirectories inside sessions/ that we skip
# Subdirectories inside sessions/ that we skip (no token data)
_SKIP_DIRS = {"bridge"}


# ── helpers ──────────────────────────────────────────────────────────────


def _parse_hanako_line(line: str) -> dict | None:
    """Parse a single JSONL line from a Hanako session/activity file.

    Returns the parsed dict if it's an ``assistant`` message with usage data,
    ``None`` otherwise.
    """
    line = line.strip()
    if not line:
        return None

    # Quick filter: skip non-assistant lines early
    if '"type":"message"' not in line and '"type": "message"' not in line:
        return None
    if '"role":"assistant"' not in line and '"role": "assistant"' not in line:
        return None
    if '"usage"' not in line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    if data.get("type") != "message":
        return None

    msg = data.get("message", {})
    if msg.get("role") != "assistant":
        return None

    usage = msg.get("usage", {})
    if not usage:
        return None

    return data


def _build_record(data: dict, agent_name: str) -> TokenRecord | None:
    """Build a TokenRecord from a parsed Hanako assistant message.

    Hanako's JSONL usage schema:

    .. code-block:: json

        {
          "type": "message",
          "id": "...",
          "timestamp": "2026-05-25T00:01:44.370Z",
          "message": {
            "role": "assistant",
            "model": "openai/gpt-4o",
            "provider": "openrouter",
            "usage": {
              "input": 12510,
              "output": 362,
              "cacheRead": 0,
              "cacheWrite": 0,
              "totalTokens": 12872,
              "cost": {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "total": 0
              }
            },
            "stopReason": "toolUse",
            "responseId": "gen-..."
          }
        }
    """
    msg = data["message"]
    usage = msg["usage"]

    ts = data.get("timestamp", "")
    model = msg.get("model", "unknown")
    session_id = data.get("id") or data.get("parentId") or ""

    input_tokens = usage.get("input", 0) or 0
    output_tokens = usage.get("output", 0) or 0
    cache_read = usage.get("cacheRead", 0) or 0
    cache_write = usage.get("cacheWrite", 0) or 0

    # Skip all-zero records (rate-limited / errored calls that never ran)
    if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
        return None

    # Use the cost that Hanako's provider already calculated.
    # Hanako's JSONL includes cost data from the provider (e.g. OpenRouter),
    # which is more accurate than our local pricing calculation.
    cost = usage.get("cost", {})
    cost_usd = (cost.get("total", 0.0) if isinstance(cost, dict) else 0.0) or 0.0

    raw = json.dumps(
        {
            "msg_id": data.get("id", ""),
            "parent_id": data.get("parentId", ""),
            "stop_reason": msg.get("stopReason", ""),
            "response_id": msg.get("responseId", ""),
            "provider": msg.get("provider", ""),
        },
        ensure_ascii=False,
    )

    return TokenRecord(
        timestamp=ts,
        agent=agent_name,
        model=model,
        session_id=session_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=round(cost_usd, 6),
        raw_data=raw,
    )


# ── collector ────────────────────────────────────────────────────────────


class HanakoCollector(BaseCollector):
    """Collect token usage from Hanako session JSONL files.

    Reads ``~/.hanako/agents/hanako/sessions/*.jsonl`` which Hanako writes
    natively — no hooks, no config needed.

    Incremental collection via file-position watermarks: as the session file
    grows (new lines are appended), only the new portion is scanned.
    """

    @property
    def name(self) -> str:
        return "hanako"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")
        last_dt = parse_timestamp(last_ts_str)
        file_positions: dict[str, int] = state.get("file_positions", {})

        sessions_dir = Path.home() / ".hanako" / "agents" / "hanako" / "sessions"
        if not sessions_dir.exists():
            logger.debug("Hanako: sessions dir not found at %s", sessions_dir)
            return []

        records: list[TokenRecord] = []
        max_ts_str = ""
        new_positions: dict[str, int] = {}

        # Collect all .jsonl files recursively, excluding archived/bridge dirs
        jsonl_files: list[Path] = []
        for child in sorted(sessions_dir.iterdir()):
            if child.is_dir():
                if child.name in _SKIP_DIRS:
                    continue
                jsonl_files.extend(sorted(child.glob("*.jsonl")))
            elif child.suffix == ".jsonl":
                jsonl_files.append(child)

        logger.debug("Hanako: scanning %d jsonl files in %s", len(jsonl_files), sessions_dir)

        for fpath in jsonl_files:
            # Build a relative key that survives directory structure changes
            rel_key = str(fpath.relative_to(sessions_dir))
            start_pos = file_positions.get(rel_key, 0)

            try:
                file_size = fpath.stat().st_size
            except OSError:
                continue

            # File was truncated or replaced — reset position
            if start_pos > file_size:
                start_pos = 0

            # Skip fully-read files that haven't grown
            if start_pos == file_size:
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    if start_pos > 0:
                        f.seek(start_pos)

                    for line in f:
                        data = _parse_hanako_line(line)
                        if data is None:
                            continue

                        ts = data.get("timestamp", "")
                        ts_dt = parse_timestamp(ts)
                        if ts_dt <= last_dt:
                            continue

                        record = _build_record(data, self.name)
                        if record is not None:
                            records.append(record)
                            if not max_ts_str or ts_dt > parse_timestamp(max_ts_str):
                                max_ts_str = ts

                    new_positions[rel_key] = f.tell()

            except OSError as e:
                logger.warning("Hanako: failed to read %s: %s", fpath, e)
                continue

        if records:
            self._save_state({
                "last_timestamp": max_ts_str,
                "file_positions": new_positions,
            })

        logger.info("Hanako: collected %d new records", len(records))
        return records