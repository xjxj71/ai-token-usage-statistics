from __future__ import annotations

import json
import logging
import shutil
import tempfile
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

        db_path = self._resolve_db_path()
        if db_path is None:
            return []

        tmp_path = await self._copy_to_temp(db_path)
        if tmp_path is None:
            return []

        try:
            records = await self._read_new_records(tmp_path, last_row_id)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if records:
            max_id = max(r.raw_data.get("_row_id", 0) for r in records if r.raw_data)
            self._save_state({"last_row_id": max_id})

        return records

    def _resolve_db_path(self) -> str | None:
        base = f"{settings.wsl_root}\\home"
        if settings.wsl_user:
            path = Path(f"{base}\\{settings.wsl_user}\\.hermes\\state.db")
            if path.exists():
                return str(path)

        try:
            home = Path(base)
            for user_dir in home.iterdir():
                candidate = user_dir / ".hermes" / "state.db"
                if candidate.exists():
                    return str(candidate)
        except OSError:
            pass

        return None

    async def _copy_to_temp(self, db_path: str) -> str | None:
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
                rows = await db.execute_fetchall(
                    """SELECT rowid, input_tokens, output_tokens,
                              cache_read_tokens, cache_write_tokens,
                              estimated_cost_usd, actual_cost_usd,
                              created_at, model, session_id
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

                ts = row["created_at"] or ""
                if not ts:
                    from datetime import datetime, timezone
                    ts = datetime.now(timezone.utc).isoformat()

                records.append(
                    TokenRecord(
                        timestamp=ts,
                        agent=self.name,
                        model=model,
                        session_id=str(row["session_id"] or ""),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                        cost_usd=round(cost, 6),
                        raw_data=json.dumps({"_row_id": row_id}, ensure_ascii=False),
                    )
                )

        return records
