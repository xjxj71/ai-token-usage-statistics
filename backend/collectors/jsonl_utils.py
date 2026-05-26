"""Shared JSONL parsing utilities for collectors that read session files."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)

# Magic number for detecting millisecond epoch timestamps
_MS_EPOCH_THRESHOLD = 1e12


def parse_timestamp(ts: str | int | float) -> datetime:
    """Parse a timestamp — handles ISO strings, second/millisecond epoch ints.

    Falls back to epoch on failure with a warning log.
    """
    if isinstance(ts, (int, float)):
        if ts > _MS_EPOCH_THRESHOLD:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        logger.debug("Failed to parse timestamp: %s", ts)
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_jsonl_line(line: str) -> dict | None:
    """Parse a single JSONL line, returning None if it's not a valid assistant message with usage."""
    line = line.strip()
    if not line:
        return None

    # Quick filter: skip non-assistant lines early
    if '"type":"assistant"' not in line and '"type": "assistant"' not in line:
        return None
    # Quick filter: must have usage data
    if "input_tokens" not in line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    if data.get("type") != "assistant":
        return None

    usage = data.get("message", {}).get("usage", {})
    if not usage:
        return None

    return data


def build_token_record(
    data: dict,
    agent_name: str,
    include_metadata: bool = True,
) -> TokenRecord | None:
    """Build a TokenRecord from a parsed JSONL assistant message.

    Returns None if the record is all-zero (empty session).
    """
    usage = data["message"]["usage"]
    ts = data.get("timestamp", "")
    model = data.get("message", {}).get("model", "unknown")
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)

    # Skip all-zero records
    if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
        return None

    cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

    raw_data = ""
    if include_metadata:
        meta = {
            "uuid": data.get("uuid", ""),
            "sessionId": data.get("sessionId", ""),
            "version": data.get("version", ""),
            "entrypoint": data.get("entrypoint", ""),
            "isSidechain": data.get("isSidechain", False),
            "agentId": data.get("agentId", ""),
            "slug": data.get("slug", ""),
            "cwd": data.get("cwd", ""),
            "gitBranch": data.get("gitBranch", ""),
        }
        raw_data = json.dumps(meta, ensure_ascii=False)

    return TokenRecord(
        timestamp=ts,
        agent=agent_name,
        model=model,
        session_id=data.get("sessionId", ""),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=round(cost, 6),
        raw_data=raw_data,
    )


def scan_jsonl_directory(
    projects_dir: Path,
    agent_name: str,
    last_dt: datetime,
    file_positions: dict[str, int],
    include_metadata: bool = True,
) -> tuple[list[TokenRecord], dict[str, int], str]:
    """Scan a directory of JSONL files for new token records.

    Args:
        projects_dir: Root directory to scan for .jsonl files
        agent_name: Agent name to set on records
        last_dt: Only records after this datetime are collected
        file_positions: Previous file position watermarks for incremental reads
        include_metadata: Whether to include raw_data metadata

    Returns:
        (records, new_positions, max_timestamp_string)
    """
    records: list[TokenRecord] = []
    max_ts_str = ""
    new_positions: dict[str, int] = {}

    jsonl_files = sorted(projects_dir.rglob("*.jsonl"))
    logger.debug("%s: scanning %d jsonl files", agent_name, len(jsonl_files))

    for fpath in jsonl_files:
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

                for _line_no, line in enumerate(f, 1):
                    data = parse_jsonl_line(line)
                    if data is None:
                        continue

                    ts = data.get("timestamp", "")
                    ts_dt = parse_timestamp(ts)
                    if ts_dt <= last_dt:
                        continue

                    record = build_token_record(data, agent_name, include_metadata)
                    if record is not None:
                        records.append(record)
                        if not max_ts_str or ts_dt > parse_timestamp(max_ts_str):
                            max_ts_str = ts

                # Record current position for incremental reads
                new_positions[rel_key] = f.tell()

        except OSError as e:
            logger.warning("%s: failed to read %s: %s", agent_name, fpath, e)
            continue

    return records, new_positions, max_ts_str
