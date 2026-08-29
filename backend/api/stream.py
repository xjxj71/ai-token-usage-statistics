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

# One queue per connected SSE client. A single shared asyncio.Event would let
# one client's clear() swallow notifications intended for other clients.
_subscribers: set[asyncio.Queue[bool]] = set()


def notify_new_records() -> None:
    """Called by the polling loop after a collection cycle with new records."""
    for q in list(_subscribers):
        q.put_nowait(True)


@router.get("/stream")
async def stream_events():
    polling_active = is_polling_active()

    async def event_generator():
        if not polling_active:
            # No background polling — let clients know collection is disabled
            # to avoid concurrent collectors being triggered by every SSE
            # connection simultaneously.
            data = json.dumps({"type": "polling_disabled", "message": "Background collection is not running."})
            yield f"data: {data}\n\n"
            return

        queue: asyncio.Queue[bool] = asyncio.Queue()
        _subscribers.add(queue)
        try:
            while True:
                try:
                    # Heartbeat if no notification arrives within the poll
                    # interval — keeps proxies from closing the connection.
                    notified = await asyncio.wait_for(
                        queue.get(), timeout=settings.poll_interval_seconds
                    )
                    if notified:
                        yield f"data: {json.dumps({'type': 'new_records'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                except TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                except Exception:
                    logger.exception("SSE event generator error")
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Internal server error'})}\n\n"
        finally:
            _subscribers.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
