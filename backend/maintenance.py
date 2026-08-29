"""Data retention and backup maintenance.

Retention aggregates raw ``token_usage`` rows older than the cutoff into
``usage_daily`` (one row per Shanghai day × agent × model × project) and then
deletes them — aggregate reads UNION both tables (see
``backend.db.models._usage_source``) so trends and totals keep full history
while the raw-detail tables stay bounded.

Backups use SQLite's online backup API into ``data/backups/``, keeping the
newest N files.  A background task runs retention + auto-backup at most once
every 24 hours.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from backend.config import settings
from backend.db import database as db_module

logger = logging.getLogger(__name__)

_MAINTENANCE_INTERVAL_SECONDS = 3600
_MAINTENANCE_MIN_GAP_SECONDS = 24 * 3600

_BACKUP_NAME_RE = re.compile(r"^token_statistic_\d{8}_\d{6}\.db$")

# Shanghai-day expression shared with fetch_trend (UTC → +8 → date part)
_DAY_EXPR = "substr(datetime(replace(substr(timestamp,1,19),'T',' '),'+8 hours'),1,10)"

_DEFAULT_APP_SETTINGS: dict = {
    "retention_days": 0,  # 0 = keep raw records forever
    "backup_keep": 10,
    "auto_backup": True,
}

_ENV_OVERRIDES = {
    "retention_days": "TOKEN_STAT_RETENTION_DAYS",
    "backup_keep": "TOKEN_STAT_BACKUP_KEEP",
    "auto_backup": "TOKEN_STAT_AUTO_BACKUP",
}

_task: asyncio.Task | None = None


# ── App settings (runtime-editable, persisted next to the DB) ───────


def _app_settings_path() -> Path:
    return settings.db_path.parent / "app_settings.json"


def _read_app_settings_file() -> dict:
    try:
        data = json.loads(_app_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in _DEFAULT_APP_SETTINGS if k in data}


def get_app_settings() -> dict:
    """Effective settings: defaults ← persisted file ← environment variables."""
    merged = dict(_DEFAULT_APP_SETTINGS)
    merged.update(_read_app_settings_file())
    for key, env_name in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        # bool must be checked before int — bool is an int subclass
        if isinstance(_DEFAULT_APP_SETTINGS[key], bool):
            merged[key] = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            try:
                merged[key] = int(raw)
            except ValueError:
                logger.warning("Ignoring invalid %s=%r", env_name, raw)
    return merged


async def update_app_settings(updates: dict) -> dict:
    """Validate and persist a partial settings update, returning effective values."""
    current = _read_app_settings_file()

    for key in ("retention_days", "backup_keep"):
        if key in updates and updates[key] is not None:
            value = int(updates[key])
            if value < 0 or (key == "backup_keep" and value < 1):
                raise ValueError(f"{key} must be a positive integer")
            current[key] = value
    if "auto_backup" in updates and updates["auto_backup"] is not None:
        current["auto_backup"] = bool(updates["auto_backup"])

    path = _app_settings_path()
    try:
        await asyncio.to_thread(
            lambda: (path.parent.mkdir(parents=True, exist_ok=True),
                     path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8"))
        )
    except OSError as e:
        raise RuntimeError(f"Failed to persist settings: {e}") from e
    return get_app_settings()


# ── Retention ───────────────────────────────────────────────────


async def run_retention(retention_days: int) -> dict:
    """Archive-then-delete raw records older than ``retention_days`` days."""
    if retention_days <= 0:
        return {"disabled": True, "archived_rows": 0, "deleted_rows": 0}

    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db = await db_module.get_db()

    archive_sql = f"""
        INSERT INTO usage_daily
            (date, agent, model, project,
             input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
             reasoning_tokens, cost_usd, call_count)
        SELECT {_DAY_EXPR}, t.agent, t.model, t.project,
               SUM(t.input_tokens), SUM(t.output_tokens),
               SUM(t.cache_read_tokens), SUM(t.cache_write_tokens),
               SUM(t.reasoning_tokens),
               SUM(
                   t.input_tokens      * COALESCE(p.input_price, 0)      / 1000000.0 +
                   t.output_tokens     * COALESCE(p.output_price, 0)     / 1000000.0 +
                   t.cache_read_tokens * COALESCE(p.cache_read_price, 0) / 1000000.0 +
                   t.cache_write_tokens* COALESCE(p.cache_write_price,0) / 1000000.0
               ),
               COUNT(*)
        FROM token_usage t
        LEFT JOIN model_pricing p ON t.model = p.model
        WHERE t.timestamp < ?
        GROUP BY 1, t.agent, t.model, t.project
        ON CONFLICT(date, agent, model, project) DO UPDATE SET
            input_tokens       = input_tokens       + excluded.input_tokens,
            output_tokens      = output_tokens      + excluded.output_tokens,
            cache_read_tokens  = cache_read_tokens  + excluded.cache_read_tokens,
            cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens,
            reasoning_tokens   = reasoning_tokens   + excluded.reasoning_tokens,
            cost_usd           = cost_usd           + excluded.cost_usd,
            call_count         = call_count         + excluded.call_count
    """
    archive_cur = await db.execute(archive_sql, (cutoff,))
    archived = archive_cur.rowcount or 0

    delete_cur = await db.execute("DELETE FROM token_usage WHERE timestamp < ?", (cutoff,))
    deleted = delete_cur.rowcount or 0
    await db.commit()

    # Reclaim disk space; harmless to fail (e.g. locked file on Windows)
    try:
        await db.execute("VACUUM")
    except aiosqlite.Error as e:
        logger.warning("VACUUM after retention failed: %s", e)

    logger.info("Retention: archived %d rows / deleted %d rows older than %s", archived, deleted, cutoff)
    return {"retention_days": retention_days, "cutoff": cutoff,
            "archived_rows": archived, "deleted_rows": deleted}


# ── Backups ─────────────────────────────────────────────────────


def _backup_dir() -> Path:
    d = settings.db_path.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_backups() -> list[dict]:
    """Newest-first list of backup files with size and mtime."""
    items = []
    for f in _backup_dir().iterdir():
        if not _BACKUP_NAME_RE.match(f.name):
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        items.append({
            "name": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        })
    items.sort(key=lambda x: x["name"], reverse=True)
    return items


def _prune_backups(keep: int) -> int:
    removed = 0
    for item in list_backups()[max(keep, 0):]:
        try:
            (_backup_dir() / item["name"]).unlink()
            removed += 1
        except OSError as e:
            logger.warning("Failed to prune backup %s: %s", item["name"], e)
    return removed


def is_valid_backup_name(name: str) -> bool:
    return bool(_BACKUP_NAME_RE.match(name))


async def create_backup() -> dict:
    """Snapshot the live database via SQLite's online backup API."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dest_path = _backup_dir() / f"token_statistic_{timestamp}.db"

    src = await db_module.get_db()
    dest = await aiosqlite.connect(str(dest_path))
    try:
        await src.backup(dest)
    finally:
        await dest.close()

    keep = int(get_app_settings().get("backup_keep", _DEFAULT_APP_SETTINGS["backup_keep"]))
    pruned = _prune_backups(keep)

    info = {
        "name": dest_path.name,
        "size_bytes": dest_path.stat().st_size,
        "created_at": datetime.now(UTC).isoformat(),
    }
    logger.info("Backup created: %s (%d old backups pruned)", info["name"], pruned)
    return info


# ── Background task ──────────────────────────────────────────────


def _state_path() -> Path:
    return settings.db_path.parent / "maintenance_state.json"


def _seconds_since_last_run() -> float:
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        last = datetime.fromisoformat(state["last_run"])
        return (datetime.now(UTC) - last).total_seconds()
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return float("inf")


def _mark_run() -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"last_run": datetime.now(UTC).isoformat()}), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("Failed to persist maintenance state: %s", e)


async def run_maintenance_cycle() -> dict:
    """One retention + auto-backup pass, honoring current settings."""
    app = get_app_settings()
    result: dict = {"retention": None, "backup": None}
    if app["retention_days"] > 0:
        result["retention"] = await run_retention(app["retention_days"])
    if app["auto_backup"]:
        result["backup"] = await create_backup()
    _mark_run()
    return result


async def _maintenance_loop() -> None:
    while True:
        try:
            if _seconds_since_last_run() >= _MAINTENANCE_MIN_GAP_SECONDS:
                await run_maintenance_cycle()
        except Exception:
            logger.exception("Maintenance cycle failed")
        await asyncio.sleep(_MAINTENANCE_INTERVAL_SECONDS)


def start_maintenance() -> bool:
    global _task
    if _task is not None and not _task.done():
        return False
    _task = asyncio.get_running_loop().create_task(_maintenance_loop())
    return True


def stop_maintenance() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
