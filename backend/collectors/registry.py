from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.claude_code import ClaudeCodeCollector
from backend.collectors.hermes import HermesCollector
from backend.collectors.openclaw import OpenClawCollector
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import TokenRecord, insert_records

logger = logging.getLogger(__name__)

COLLECTORS: list[BaseCollector] = [
    ClaudeCodeCollector(),
    HermesCollector(),
    OpenClawCollector(),
]

_task: asyncio.Task | None = None


async def run_collection_cycle() -> int:
    db = await get_db()
    total_new = 0

    for collector in COLLECTORS:
        try:
            records: Sequence[TokenRecord] = await collector.collect()
            if records:
                await insert_records(db, records)
                total_new += len(records)
                logger.info("Collected %d records from %s", len(records), collector.name)
        except Exception as e:
            logger.error("Collector %s failed: %s", collector.name, e, exc_info=True)

    return total_new


async def _poll_loop() -> None:
    while True:
        try:
            await run_collection_cycle()
        except Exception as e:
            logger.error("Collection cycle error: %s", e, exc_info=True)
        await asyncio.sleep(settings.poll_interval_seconds)


def start_polling() -> None:
    global _task
    _task = asyncio.get_event_loop().create_task(_poll_loop())


def stop_polling() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
