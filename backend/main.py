from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import paths
from backend.api import (
    cache_ratio,
    maintenance,
    models,
    quota,
    report,
    sessions,
    stream,
    summary,
    trend,
    usage,
)
from backend.collectors.registry import start_polling, stop_polling
from backend.config import settings
from backend.db.database import close_db, init_db
from backend.maintenance import start_maintenance, stop_maintenance


class FrontendStaticFiles(StaticFiles):
    """index.html 协商缓存（应用更新后普通刷新即拿新前端）；哈希资源长期缓存。"""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # 按 content-type 判断而非路径：starlette 各版本对目录路径的规范化不同；
        # Windows 下 path 可能带反斜杠，先统一分隔符。
        norm = path.replace("\\", "/")
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif norm.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
from backend.pricing.refresh import start_pricing_loop, stop_pricing_loop
from backend.quota.multipliers import start_refresh_loop, stop_refresh_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_polling()
    start_maintenance()
    # 模型消耗倍率后台同步：启动即拉取官方文档，之后按周期刷新；
    # 失败时沿用缓存/内置快照，不会阻塞启动。
    start_refresh_loop()
    # 模型定价每日自动刷新（当天手动刷新过则跳过）；启动即检查一次。
    start_pricing_loop()

    # Warm the exchange-rate cache in the background; failures fall back to
    # the configured static rate, so nothing needs to be awaited or surfaced.
    from backend.exchange_rate import get_rate

    async def _warm_rate() -> None:
        try:
            await get_rate()
        except Exception:  # warm-up only; reads fall back to the static rate
            logger.debug("Exchange rate warm-up failed", exc_info=True)

    warmup_task = asyncio.create_task(_warm_rate())
    yield
    warmup_task.cancel()
    stop_pricing_loop()
    stop_refresh_loop()
    stop_maintenance()
    stop_polling()
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="AI Token 用量统计", version="0.1.0", lifespan=lifespan)

    # Cross-origin access for the Svelte frontend.
    # In production, set TOKEN_STAT_CORS_ORIGINS to the actual domain(s).
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler — prevents stack traces leaking to clients
    # Excludes HTTPException so FastAPI returns correct status codes (404, 422, etc.)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, (HTTPException, StarletteHTTPException)):
            raise exc
        logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
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
        # Skip auth for frontend static files and docs (non-/api paths)
        if not request.url.path.startswith("/api/"):
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
    app.include_router(sessions.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
    app.include_router(stream.router, prefix="/api")
    app.include_router(trend.router, prefix="/api")
    app.include_router(cache_ratio.router, prefix="/api")
    app.include_router(quota.router, prefix="/api")
    app.include_router(report.router, prefix="/api")
    app.include_router(maintenance.router, prefix="/api")

    frontend_dist = paths.frontend_dist()
    if frontend_dist.exists():
        app.mount("/", FrontendStaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
