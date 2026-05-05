from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.collectors.registry import _task, run_collection_cycle
from backend.config import settings

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
    polling_active = _task is not None

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
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        else:
            # No background polling — SSE endpoint triggers collection itself.
            while True:
                try:
                    new_count = await run_collection_cycle()
                    if new_count > 0:
                        data = json.dumps({"type": "new_records", "count": new_count})
                        yield f"data: {data}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

                await asyncio.sleep(settings.poll_interval_seconds)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
