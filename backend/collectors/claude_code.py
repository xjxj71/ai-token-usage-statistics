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


class ClaudeCodeCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "claude-code"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts = state.get("last_timestamp", "")

        json_dir = self._wsl_path("home")
        if settings.wsl_user:
            json_dir = f"{settings.wsl_root}\\home\\{settings.wsl_user}\\.claude\\token-statistic"
        else:
            json_dir = f"{settings.wsl_root}\\home"

        try:
            wsl_home = Path(json_dir)
            if not wsl_home.exists():
                return []
        except OSError:
            return []

        token_dir = wsl_home / ".claude" / "token-statistic"
        if not token_dir.exists():
            return []

        records: list[TokenRecord] = []
        for json_file in sorted(token_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                ts = data.get("timestamp", "")
                if ts <= last_ts:
                    continue

                usage = data.get("usage", {})
                model = data.get("model", "unknown")

                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_write = usage.get("cache_creation_input_tokens", 0)

                cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

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
                        cost_usd=cost,
                        raw_data=json.dumps(data, ensure_ascii=False),
                    )
                )
                last_ts = max(last_ts, ts)

            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning("Failed to parse %s: %s", json_file, e)

        if records:
            self._save_state({"last_timestamp": last_ts})

        return records
