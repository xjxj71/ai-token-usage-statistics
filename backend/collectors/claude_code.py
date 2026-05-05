from __future__ import annotations

import json
import logging
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
    @property
    def name(self) -> str:
        return "claude-code"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")
        last_dt = _parse_ts(last_ts_str)

        costs_path = Path(settings.claude_costs_path)
        if not costs_path.exists():
            logger.debug("Claude Code: costs.jsonl not found at %s", costs_path)
            return []

        records: list[TokenRecord] = []
        max_ts_str = last_ts_str

        try:
            text = costs_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Claude Code: failed to read costs.jsonl: %s", e)
            return []

        for line_no, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("Claude Code: line %d parse error: %s", line_no, e)
                continue

            ts = data.get("timestamp", "")
            ts_dt = _parse_ts(ts)
            if ts_dt <= last_dt:
                continue

            model = data.get("model", "unknown")
            input_tokens = data.get("input_tokens", 0)
            output_tokens = data.get("output_tokens", 0)
            estimated_cost = data.get("estimated_cost_usd", 0)

            # costs.jsonl doesn't have cache token fields
            cache_read = 0
            cache_write = 0

            cost = estimated_cost if estimated_cost and estimated_cost > 0 else calculate_cost(
                model, input_tokens, output_tokens, cache_read, cache_write
            )

            records.append(
                TokenRecord(
                    timestamp=ts,
                    agent=self.name,
                    model=model,
                    session_id=data.get("session_id", ""),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                    cost_usd=round(cost, 6),
                    raw_data=json.dumps(data, ensure_ascii=False),
                )
            )
            if ts_dt > _parse_ts(max_ts_str):
                max_ts_str = ts

        if records:
            self._save_state({"last_timestamp": max_ts_str})

        return records
