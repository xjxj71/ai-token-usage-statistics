from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api import models, stream, summary, usage
from backend.collectors.registry import start_polling, stop_polling
from backend.config import settings
from backend.db.database import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_polling()
    yield
    stop_polling()
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="AI Token 用量统计", version="0.1.0", lifespan=lifespan)

    app.include_router(summary.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
    app.include_router(stream.router, prefix="/api")

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
