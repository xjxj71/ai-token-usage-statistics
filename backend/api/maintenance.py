"""Data-management endpoints: retention, backups, and app settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.deps import require_local_or_key
from backend.config import settings
from backend.maintenance import (
    create_backup,
    get_app_settings,
    is_valid_backup_name,
    list_backups,
    run_retention,
    update_app_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maintenance"])


@router.get("/config/data")
async def get_data_settings():
    """Return effective data-management settings (retention / backups)."""
    return get_app_settings()


class DataSettingsUpdate(BaseModel):
    retention_days: int | None = None
    backup_keep: int | None = None
    auto_backup: bool | None = None


@router.put("/config/data")
async def put_data_settings(body: DataSettingsUpdate, request: Request):
    """Update data-management settings, persisted to data/app_settings.json."""
    require_local_or_key(request)
    try:
        effective = await update_app_settings(body.model_dump())
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "settings": effective}


@router.post("/maintenance/cleanup")
async def run_cleanup(request: Request, days: int | None = Query(None)):
    """Run the retention pass now (archive + delete old raw records)."""
    require_local_or_key(request)
    retention_days = days if days is not None and days > 0 else get_app_settings()["retention_days"]
    if retention_days <= 0:
        raise HTTPException(
            status_code=400,
            detail="未启用数据保留策略：请先设置 retention_days（0 表示永久保留）",
        )
    result = await run_retention(int(retention_days))
    return {"status": "ok", "result": result}


@router.post("/backup")
async def backup_now(request: Request):
    """Create a database backup immediately."""
    require_local_or_key(request)
    try:
        info = await create_backup()
    except Exception as e:
        logger.exception("Manual backup failed")
        raise HTTPException(status_code=500, detail=f"备份失败: {e}")
    return {"status": "ok", "backup": info}


@router.get("/backups")
async def get_backups(request: Request):
    require_local_or_key(request)
    return {"items": list_backups()}


@router.get("/backups/{name}")
async def download_backup(name: str, request: Request):
    require_local_or_key(request)
    if not is_valid_backup_name(name):
        raise HTTPException(status_code=400, detail="非法的备份文件名")
    path = settings.db_path.parent / "backups" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="备份不存在")
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.delete("/backups/{name}")
async def delete_backup(name: str, request: Request):
    require_local_or_key(request)
    if not is_valid_backup_name(name):
        raise HTTPException(status_code=400, detail="非法的备份文件名")
    path = settings.db_path.parent / "backups" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="备份不存在")
    try:
        path.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    return {"status": "ok"}
