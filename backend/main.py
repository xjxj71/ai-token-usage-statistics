from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api import cache_ratio, models, stream, summary, trend, usage
from backend.collectors.registry import start_polling, stop_polling
from backend.config import settings
from backend.db.database import close_db, init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_polling()
    yield
    stop_polling()
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="AI Token 用量统计", version="0.1.0", lifespan=lifespan)

    # Global exception handler — prevents stack traces leaking to clients
    # Excludes HTTPException so FastAPI returns correct status codes (404, 422, etc.)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, (HTTPException, StarletteHTTPException)):
            raise exc
        logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # API key authentication middleware — checks at runtime so tests can
    # monkeypatch settings.api_key after app creation.
    @app.middleware("http")
    async def verify_api_key(request: Request, call_next):
        # Skip auth when no API key is configured
        if not settings.api_key:
            return await call_next(request)
        # Skip auth for frontend static files and docs
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.url.path in ("/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key") or ""
        if not secrets.compare_digest(api_key, settings.api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)

    app.include_router(summary.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
    app.include_router(stream.router, prefix="/api")
    app.include_router(trend.router, prefix="/api")
    app.include_router(cache_ratio.router, prefix="/api")

    frontend_dist = settings.frontend_dist.resolve()
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
