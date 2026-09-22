"""Tests for data retention, backups, and their API surface."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.db import database as db_module
from backend.db.models import TokenRecord, fetch_summary, insert_records
from backend.maintenance import (
    create_backup,
    get_app_settings,
    list_backups,
    run_retention,
    update_app_settings,
)

# Relative anchors so the suite does not depend on the wall-clock date.
_OLD_OFFSETS = (40, 39)  # days ago — always outside a short retention window
_RETENTION_DAYS = 7


def _seed_day(offset: int) -> str:
    return (datetime.now(UTC) - timedelta(days=offset)).strftime("%Y-%m-%dT10:00:00Z")


async def _seed_spanning_rows(db):
    recent = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT10:00:00Z")
    records = [
        TokenRecord(
            timestamp=_seed_day(offset), agent="zcode", model="glm-5.3",
            session_id=f"s-{offset}", project="repo-a",
            input_tokens=1000, output_tokens=500, reasoning_tokens=50,
        )
        for offset in _OLD_OFFSETS
    ]
    records.append(
        TokenRecord(
            timestamp=recent, agent="zcode", model="glm-5.3",
            session_id="s-recent", project="repo-a",
            input_tokens=1000, output_tokens=500, reasoning_tokens=50,
        )
    )
    await insert_records(db, records)


# ── Retention ────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_retention_archives_then_deletes(client):
    db = await db_module.get_db()
    await _seed_spanning_rows(db)

    # Cutoff is 7 days ago: archives the two old days, keeps yesterday
    result = await run_retention(_RETENTION_DAYS)

    assert result["deleted_rows"] == 2
    raw_left = await db.execute_fetchall("SELECT timestamp FROM token_usage")
    assert len(raw_left) == 1

    daily = await db.execute_fetchall(
        "SELECT date, input_tokens, reasoning_tokens, call_count FROM usage_daily ORDER BY date"
    )
    expected_dates = sorted(_seed_day(o)[:10] for o in _OLD_OFFSETS)
    assert [r["date"] for r in daily] == expected_dates
    assert all(r["input_tokens"] == 1000 and r["reasoning_tokens"] == 50 and r["call_count"] == 1 for r in daily)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_summary_keeps_history_after_retention(client):
    db = await db_module.get_db()
    await _seed_spanning_rows(db)

    before = await fetch_summary(db, from_ts="2000-01-01T00:00:00Z", to_ts="2100-01-01T00:00:00Z")
    total_before = sum(r.input_tokens for r in before)

    await run_retention(_RETENTION_DAYS)

    # Same wide range — the UNION with usage_daily must preserve totals
    after = await fetch_summary(db, from_ts="2000-01-01T00:00:00Z", to_ts="2100-01-01T00:00:00Z")
    assert sum(r.input_tokens for r in after) == total_before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_retention_zero_days_is_noop(client):
    db = await db_module.get_db()
    await _seed_spanning_rows(db)
    result = await run_retention(0)
    assert result["disabled"] is True
    rows = await db.execute_fetchall("SELECT COUNT(*) AS c FROM token_usage")
    assert rows[0]["c"] == 3


# ── App settings ─────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_settings_roundtrip(client):
    defaults = get_app_settings()
    assert defaults["retention_days"] == 0
    assert defaults["auto_backup"] is True

    effective = await update_app_settings({"retention_days": 90, "backup_keep": 3})
    assert effective["retention_days"] == 90
    assert effective["backup_keep"] == 3
    assert effective["auto_backup"] is True  # untouched

    with pytest.raises(ValueError):
        await update_app_settings({"retention_days": -5})
    with pytest.raises(ValueError):
        await update_app_settings({"backup_keep": 0})


# ── Backups + API ────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backup_create_list_delete(client):
    db = await db_module.get_db()
    await insert_records(
        db,
        [TokenRecord(timestamp="2026-05-02T10:00:00Z", agent="zcode", model="glm-5.3", input_tokens=10)],
    )

    res = await client.post("/api/backup")
    assert res.status_code == 200
    name = res.json()["backup"]["name"]
    assert name.startswith("token_statistic_") and name.endswith(".db")

    res = await client.get("/api/backups")
    assert res.status_code == 200
    assert any(b["name"] == name for b in res.json()["items"])

    res = await client.get(f"/api/backups/{name}")
    assert res.status_code == 200

    # Path-traversal style names are rejected before touching the filesystem
    res = await client.get("/api/backups/..%5Cevil.db")
    assert res.status_code == 400

    res = await client.delete(f"/api/backups/{name}")
    assert res.status_code == 200
    assert all(b["name"] != name for b in list_backups())

    res = await client.delete(f"/api/backups/{name}")
    assert res.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backup_pruning_keeps_newest(client):
    await update_app_settings({"backup_keep": 2})

    names = []
    for _ in range(3):
        # Backup names have second granularity — space creations apart
        await asyncio.sleep(1.05)
        info = await create_backup()
        names.append(info["name"])

    remaining = [b["name"] for b in list_backups()]
    assert len(remaining) == 2
    assert names[0] not in remaining
    assert names[1] in remaining and names[2] in remaining


@pytest.mark.integration
@pytest.mark.asyncio
async def test_maintenance_cleanup_endpoint(client):
    db = await db_module.get_db()
    await _seed_spanning_rows(db)

    res = await client.post(f"/api/maintenance/cleanup?days={_RETENTION_DAYS}")
    assert res.status_code == 200
    assert res.json()["result"]["deleted_rows"] == 2

    # No days param and no configured policy → 400
    res = await client.post("/api/maintenance/cleanup")
    assert res.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_data_settings_endpoints(client):
    res = await client.get("/api/config/data")
    assert res.status_code == 200
    assert "retention_days" in res.json()

    res = await client.put("/api/config/data", json={"retention_days": 30})
    assert res.status_code == 200
    assert res.json()["settings"]["retention_days"] == 30

    res = await client.put("/api/config/data", json={"retention_days": -1})
    assert res.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backup_remote_requires_key():
    from httpx import ASGITransport, AsyncClient

    from backend.main import app

    transport = ASGITransport(app=app, client=("10.0.0.5", 1234))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/api/backup")
        assert res.status_code == 403
        res = await c.get("/api/backups")
        assert res.status_code == 403
        res = await c.get("/api/backups/token_statistic_20260101_000000.db")
        assert res.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pricing_write_remote_requires_key():
    from httpx import ASGITransport, AsyncClient

    from backend import config
    from backend.main import app

    transport = ASGITransport(app=app, client=("10.0.0.5", 1234))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.put(
            "/api/pricing/some-model",
            json={"input_price": 1, "output_price": 1},
        )
        assert res.status_code == 403

        res = await c.post("/api/pricing/refresh")
        assert res.status_code == 403

        config.settings.api_key = "test-secret-key"
        try:
            res = await c.post(
                "/api/pricing/refresh", headers={"X-API-Key": "test-secret-key"}
            )
            assert res.status_code != 403
        finally:
            config.settings.api_key = ""
