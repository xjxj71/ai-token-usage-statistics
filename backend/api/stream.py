from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.collectors.registry import is_polling_active
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

# Shared event to notify SSE clients when the polling loop collects new records.
_new_records_event: asyncio.Event = asyncio.Event()


def notify_new_records() -> None:
    """Called by the polling loop after a collection cycle with new records."""
    _new_records_event.set()


async def _wait_for_notification(timeout: float) -> bool:
    """Wait up to *timeout* seconds for a notification. Returns True if notified."""
    try:
        await asyncio.wait_for(_new_records_event.wait(), timeout=timeout)
        _new_records_event.clear()
        return True
    except asyncio.TimeoutError:
        return False


@router.get("/stream")
async def stream_events():
    polling_active = is_polling_active()

    async def event_generator():
        if polling_active:
            # Polling loop owns collection — just wait for notifications.
            while True:
                try:
                    notified = await _wait_for_notification(settings.poll_interval_seconds)
                    if notified:
                        data = json.dumps({"type": "new_records"})
                        yield f"data: {data}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                except Exception as e:
                    logger.error("SSE event generator error: %s", e, exc_info=True)
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Internal server error'})}\n\n"
        else:
            # No background polling — let clients know collection is disabled
            # to avoid concurrent collectors being triggered by every SSE
            # connection simultaneously.
            data = json.dumps({"type": "polling_disabled", "message": "Background collection is not running."})
            yield f"data: {data}\n\n"
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
