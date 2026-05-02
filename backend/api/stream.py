from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.collectors.registry import run_collection_cycle
from backend.config import settings

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream_events():
    async def event_generator():
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
