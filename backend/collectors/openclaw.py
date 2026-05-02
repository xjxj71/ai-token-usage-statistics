from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
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
        last_ts = state.get("last_timestamp", "")

        sessions_dir = self._resolve_sessions_dir()
        if sessions_dir is None:
            return []

        records: list[TokenRecord] = []
        max_ts = last_ts

        for agent_dir in sorted(sessions_dir.iterdir()):
            if not agent_dir.is_dir():
                continue

            sessions_file = agent_dir / "sessions" / "sessions.json"
            if not sessions_file.exists():
                continue

            try:
                data = json.loads(sessions_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read %s: %s", sessions_file, e)
                continue

            sessions = data if isinstance(data, list) else data.get("sessions", [])
            for session in sessions:
                ts = session.get("updatedAt", session.get("createdAt", ""))
                if ts <= last_ts:
                    continue

                model = session.get("model", "unknown")
                input_tokens = session.get("inputTokens", 0)
                output_tokens = session.get("outputTokens", 0)
                cache_read = session.get("cacheRead", 0)
                cache_write = session.get("cacheWrite", 0)
                cost = session.get("estimatedCostUsd", 0)

                if cost <= 0:
                    cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

                records.append(
                    TokenRecord(
                        timestamp=ts,
                        agent=self.name,
                        model=model,
                        session_id=session.get("id", ""),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                        cost_usd=round(cost, 6),
                        raw_data=json.dumps(session, ensure_ascii=False),
                    )
                )
                max_ts = max(max_ts, ts)

        if records:
            self._save_state({"last_timestamp": max_ts})

        return records

    def _resolve_sessions_dir(self) -> Path | None:
        base = f"{settings.wsl_root}\\home"
        if settings.wsl_user:
            path = Path(f"{base}\\{settings.wsl_user}\\.openclaw\\agents")
            if path.exists():
                return path

        try:
            home = Path(base)
            for user_dir in home.iterdir():
                candidate = user_dir / ".openclaw" / "agents"
                if candidate.exists():
                    return candidate
        except OSError:
            pass

        return None
