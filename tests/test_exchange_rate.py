"""Tests for the exchange-rate module and its API surface."""

import pytest

import backend.exchange_rate as fx
from backend import config


@pytest.fixture(autouse=True)
def _reset_fx_state(tmp_path, monkeypatch):
    """Isolate module state and persistence per test."""
    fx.reset_cache()
    monkeypatch.setattr(config.settings, "db_path", tmp_path / "test.db")
    yield
    fx.reset_cache()


def _mock_live(monkeypatch, rate: float):
    def _fake():
        return rate

    monkeypatch.setattr(fx, "_fetch_live_blocking", _fake)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_rate_fetches_live_and_persists(monkeypatch):
    _mock_live(monkeypatch, 7.1)
    info = await fx.get_rate()
    assert info.rate == 7.1
    assert info.source == "live"
    assert info.fetched_at != ""

    # Persisted for offline restarts
    persisted = fx._load_persisted()
    assert persisted is not None
    assert persisted.rate == 7.1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_rate_uses_cache_within_ttl(monkeypatch):
    calls = []

    def _fake():
        calls.append(1)
        return 7.2

    monkeypatch.setattr(fx, "_fetch_live_blocking", _fake)

    await fx.get_rate()
    await fx.get_rate()
    assert len(calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_rate_force_bypasses_cache(monkeypatch):
    calls = []

    def _fake():
        calls.append(1)
        return 7.3

    monkeypatch.setattr(fx, "_fetch_live_blocking", _fake)

    await fx.get_rate()
    await fx.get_rate(force=True)
    assert len(calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_rate_falls_back_on_fetch_failure(monkeypatch):
    def _broken():
        raise OSError("network down")

    monkeypatch.setattr(fx, "_fetch_live_blocking", _broken)
    monkeypatch.setattr(config.settings, "usd_to_cny_rate", 6.99)

    info = await fx.get_rate()
    assert info.source == "fallback"
    assert info.rate == 6.99


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_rate_prefers_persisted_over_static(monkeypatch, tmp_path):
    # A previous live fetch left a persisted value on disk
    (tmp_path / "exchange_rate.json").write_text(
        '{"rate": 7.05, "fetched_at": "2026-01-01T00:00:00+00:00"}', encoding="utf-8"
    )

    def _broken():
        raise OSError("offline")

    monkeypatch.setattr(fx, "_fetch_live_blocking", _broken)

    info = await fx.get_rate()
    assert info.source == "live"
    assert info.rate == 7.05


# ── API surface ──────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_config_returns_effective_rate(client, monkeypatch):
    _mock_live(monkeypatch, 7.15)
    res = await client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert data["usd_to_cny_rate"] == 7.15
    assert data["rate_source"] == "live"
    assert data["rate_updated_at"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exchange_rate_refresh_endpoint(client, monkeypatch):
    _mock_live(monkeypatch, 7.4)
    res = await client.post("/api/config/exchange-rate/refresh")
    assert res.status_code == 200
    data = res.json()
    assert data["usd_to_cny_rate"] == 7.4
    assert data["rate_source"] == "live"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exchange_rate_refresh_remote_requires_key(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from backend.main import app

    _mock_live(monkeypatch, 7.4)
    transport = ASGITransport(app=app, client=("10.0.0.5", 1234))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/api/config/exchange-rate/refresh")
    assert res.status_code == 403
