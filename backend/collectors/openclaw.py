from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from backend.collectors.base import BaseCollector
from backend.collectors.jsonl_utils import parse_timestamp
from backend.config import settings
from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


class OpenClawCollector(BaseCollector):
    """Collect token usage from OpenClaw sessions.json.

    ``inputTokens`` / ``outputTokens`` / ``cacheRead`` / ``cacheWrite`` /
    ``estimatedCostUsd`` are **cumulative per-session counters** (the file is
    a session registry, like Hermes' state.db).  Writing them as-is on every
    ``updatedAt`` advance counted a session's whole usage once per update —
    the same bug class fixed for Hermes in user_version 2.

    Each poll therefore derives per-session deltas against the counters
    stored in collector state (``session_counters``).  A session first seen
    with usage from before we watched it starts from its current counters
    (only later usage is written); one created since the previous poll starts
    from zero.  Counter resets clamp to zero per field.  Rows written before
    this convention are consolidated by the user_version 3 migration.
    """

    @property
    def name(self) -> str:
        return "openclaw"

    async def collect(self) -> Sequence[TokenRecord]:
        # WSL guard: bail before the wsl.exe copy — it would boot a
        # stopped WSL.
        if not await asyncio.to_thread(settings.is_wsl_running):
            logger.debug(
                "OpenClaw: WSL distro '%s' not running, skipping poll",
                settings.wsl_distro,
            )
            return []

        state = self._load_state()
        counters: dict[str, list] = state.get("session_counters", {})
        last_poll_ts: float | None = None
        if state.get("last_poll_at"):
            try:
                last_poll_ts = datetime.fromisoformat(state["last_poll_at"]).timestamp()
            except ValueError:
                last_poll_ts = None

        # Copy sessions.json from WSL /root to /tmp for UNC access
        if not await asyncio.to_thread(
            settings.wsl_copy_to_tmp,
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
            text = await asyncio.to_thread(sessions_path.read_text, "utf-8")
            data = json.loads(text)
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
        # Rebuilt from the current file every poll — sessions that disappeared
        # from the registry drop out of state instead of accumulating forever.
        new_counters: dict[str, list] = {}
        now_utc = datetime.now(UTC)

        for agent_key, session in data.items():
            if not isinstance(session, dict):
                continue

            session_id = str(session.get("sessionId", agent_key))
            model = session.get("model", "unknown")
            cur = (
                session.get("inputTokens", 0) or 0,
                session.get("outputTokens", 0) or 0,
                session.get("cacheRead", 0) or 0,
                session.get("cacheWrite", 0) or 0,
            )
            reported_cost = session.get("estimatedCostUsd", 0) or 0
            cum_cost = (
                reported_cost
                if reported_cost > 0
                else calculate_cost(model, *cur)
            )
            series = (*cur, cum_cost)

            key = f"{session_id}|{model}"
            prev = counters.get(key)
            if prev is None:
                # First sight: a session created since the previous poll
                # starts from zero; anything older may carry usage from
                # before we watched it — its current counters become the
                # baseline so pre-existing usage is not dumped into today.
                started_raw = session.get("startedAt")
                started_ts = (
                    parse_timestamp(started_raw).timestamp() if started_raw else None
                )
                is_new = (
                    last_poll_ts is not None
                    and started_ts is not None
                    and started_ts > last_poll_ts
                )
                base = (0, 0, 0, 0, 0.0) if is_new else series
            else:
                base = tuple(prev)

            delta = tuple(max(c - b, 0) for c, b in zip(series, base))
            new_counters[key] = list(series)
            if not any(delta[:4]):
                continue

            # updatedAt is millisecond epoch integer — when the usage happened
            ts_dt = parse_timestamp(session.get("updatedAt", session.get("startedAt", "")))
            records.append(
                TokenRecord(
                    timestamp=ts_dt.isoformat(),
                    agent=self.name,
                    model=model,
                    session_id=session_id,
                    input_tokens=int(delta[0]),
                    output_tokens=int(delta[1]),
                    cache_read_tokens=int(delta[2]),
                    cache_write_tokens=int(delta[3]),
                    cost_usd=round(delta[4], 6),
                    raw_data=json.dumps(
                        {
                            "agent_key": agent_key,
                            "session_id": session.get("sessionId"),
                            "mode": "delta",
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        self._save_state(
            {"session_counters": new_counters, "last_poll_at": now_utc.isoformat()}
        )
        if records:
            logger.info("OpenClaw: %d delta records from %d sessions", len(records), len(new_counters))
        return records