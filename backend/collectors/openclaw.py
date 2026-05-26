from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.jsonl_utils import parse_timestamp
from backend.config import settings
from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


class OpenClawCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "openclaw"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_str = state.get("last_timestamp", "")
        last_dt = parse_timestamp(last_ts_str)

        # Copy sessions.json from WSL /root to /tmp for UNC access
        if not settings.wsl_copy_to_tmp(
            "/root/.openclaw/agents/main/sessions/sessions.json",
            "/tmp/openclaw_sessions.json",
        ):
            logger.warning("OpenClaw: failed to copy sessions.json via wsl_copy")
            return []

        sessions_path = Path(settings.openclaw_sessions_path)
        if not sessions_path.exists():
            logger.warning("OpenClaw: copied file not accessible at %s", sessions_path)
            return []

        try:
            data = json.loads(sessions_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("OpenClaw: failed to read sessions.json: %s", e)
            return []

        # sessions.json is a dict keyed by agent session names, e.g.:
        #   {"agent:main:main": {...}, "agent:main:tui-xxx": {...}, ...}
        # NOT a list.
        if not isinstance(data, dict):
            logger.warning("OpenClaw: unexpected sessions.json format (expected dict)")
            return []

        records: list[TokenRecord] = []
        max_ts_str = last_ts_str

        for agent_key, session in data.items():
            if not isinstance(session, dict):
                continue

            # updatedAt is millisecond epoch integer
            ts_raw = session.get("updatedAt", session.get("startedAt", ""))
            ts_dt = parse_timestamp(ts_raw)
            if ts_dt <= last_dt:
                continue

            model = session.get("model", "unknown")
            input_tokens = session.get("inputTokens", 0) or 0
            output_tokens = session.get("outputTokens", 0) or 0
            cache_read = session.get("cacheRead", 0) or 0
            cache_write = session.get("cacheWrite", 0) or 0
            cost = session.get("estimatedCostUsd", 0) or 0

            if cost <= 0:
                cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

            # Convert ts to ISO string for storage
            ts_iso = ts_dt.isoformat()

            records.append(
                TokenRecord(
                    timestamp=ts_iso,
                    agent=self.name,
                    model=model,
                    session_id=str(session.get("sessionId", agent_key)),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                    cost_usd=round(cost, 6),
                    raw_data=json.dumps(
                        {"agent_key": agent_key, "session_id": session.get("sessionId")},
                        ensure_ascii=False,
                    ),
                )
            )
            if not max_ts_str or ts_dt > parse_timestamp(max_ts_str):
                max_ts_str = ts_raw

        if records:
            self._save_state({"last_timestamp": max_ts_str})

        return records
