from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import aiosqlite

from backend.collectors.base import BaseCollector
from backend.config import settings
from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


class HermesCollector(BaseCollector):
    @property
    def name(self) -> str:
        return "hermes"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_row_id = state.get("last_row_id", 0)

        # Copy state.db from WSL /root to /tmp for UNC access
        if not settings.wsl_copy_to_tmp(
            "/root/.hermes/state.db", "/tmp/hermes_state.db"
        ):
            logger.warning("Hermes: failed to copy state.db via wsl_copy")
            return []

        db_path = settings.hermes_db_path
        if not Path(db_path).exists():
            logger.warning("Hermes: copied file not accessible at %s", db_path)
            return []

        tmp_path = await self._copy_to_temp(db_path)
        if tmp_path is None:
            return []

        try:
            records = await self._read_new_records(tmp_path, last_row_id)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if records:
            raw_datas = []
            for r in records:
                if r.raw_data:
                    raw_datas.append(json.loads(r.raw_data))
            max_id = max(d.get("_row_id", 0) for d in raw_datas) if raw_datas else 0
            self._save_state({"last_row_id": max_id})

        return records

    async def _copy_to_temp(self, db_path: str) -> str | None:
        """Copy the UNC-accessible db to a local temp file for SQLite access."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            shutil.copy2(db_path, tmp.name)
            return tmp.name
        except OSError as e:
            logger.warning("Failed to copy hermes state.db: %s", e)
            return None

    async def _read_new_records(self, db_path: str, last_row_id: int) -> list[TokenRecord]:
        records: list[TokenRecord] = []

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                # Hermes sessions schema uses:
                #   started_at REAL  (Unix timestamp, e.g. 1778000332.40501)
                #   id TEXT PRIMARY KEY  (session id)
                rows = await db.execute_fetchall(
                    """SELECT rowid, input_tokens, output_tokens,
                              cache_read_tokens, cache_write_tokens,
                              estimated_cost_usd, actual_cost_usd,
                              started_at, model, id
                       FROM sessions
                       WHERE rowid > ?
                       ORDER BY rowid""",
                    [last_row_id],
                )
            except aiosqlite.OperationalError as e:
                logger.warning("Hermes DB query failed: %s", e)
                return records

            for row in rows:
                row_id = row["rowid"]
                model = row["model"] or "unknown"
                input_tokens = row["input_tokens"] or 0
                output_tokens = row["output_tokens"] or 0
                cache_read = row["cache_read_tokens"] or 0
                cache_write = row["cache_write_tokens"] or 0

                actual_cost = row["actual_cost_usd"]
                cost = actual_cost if actual_cost and actual_cost > 0 else calculate_cost(
                    model, input_tokens, output_tokens, cache_read, cache_write
                )

                # started_at is REAL (Unix timestamp), convert to ISO string
                started_at = row["started_at"]
                if started_at:
                    ts = datetime.fromtimestamp(
                        started_at, tz=timezone.utc
                    ).isoformat()
                else:
                    ts = datetime.now(timezone.utc).isoformat()

                records.append(
                    TokenRecord(
                        timestamp=ts,
                        agent=self.name,
                        model=model,
                        session_id=str(row["id"] or ""),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                        cost_usd=round(cost, 6),
                        raw_data=json.dumps({"_row_id": row_id}, ensure_ascii=False),
                    )
                )

        return records
