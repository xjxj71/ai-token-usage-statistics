"""Tests for the quota monitoring module."""

import pytest

from backend.quota.base import QuotaSnapshot, QuotaWindow
from backend.quota.registry import get_registry
from backend.quota.xiaomi import _PLAN_LIMITS_MONTHLY, XiaomiQuotaProvider
from backend.quota.zhipu import _PLAN_LIMITS, ZhipuQuotaProvider

# ── Dataclass unit tests ────────────────────────────────────────


@pytest.mark.unit
def test_quota_window_ratio():
    w = QuotaWindow(used=300, total=400, unit="prompts")
    assert w.ratio == 0.75
    assert w.remaining == 100


@pytest.mark.unit
def test_quota_window_zero_total():
    w = QuotaWindow(used=0, total=0, unit="prompts")
    assert w.ratio == 0.0
    assert w.remaining == 0.0


@pytest.mark.unit
def test_quota_snapshot_defaults():
    s = QuotaSnapshot(provider="test", display_name="Test", plan_name="Pro")
    assert s.extra_windows == []
    assert s.model_multipliers == []
    assert s.source == "api"
    assert s.error is None


# ── Provider instantiation ──────────────────────────────────────


@pytest.mark.unit
def test_zhipu_provider_config():
    p = ZhipuQuotaProvider({"enabled": True, "plan_type": "max", "session_token": "abc"})
    assert p.provider_id == "zhipu"
    assert p.enabled is True
    assert p.plan_type == "max"
    assert p.credential == "abc"


@pytest.mark.unit
def test_xiaomi_provider_config():
    p = XiaomiQuotaProvider({"enabled": False, "plan_type": "lite"})
    assert p.provider_id == "xiaomi"
    assert p.enabled is False
    assert p.plan_type == "lite"
    assert p.credential == ""


@pytest.mark.unit
def test_zhipu_plan_limits():
    assert _PLAN_LIMITS["lite"]["window_5h"] == 80
    assert _PLAN_LIMITS["pro"]["weekly"] == 2000
    assert _PLAN_LIMITS["max"]["window_5h"] == 1600


@pytest.mark.unit
def test_xiaomi_plan_limits():
    assert _PLAN_LIMITS_MONTHLY["lite"] == 4_100_000_000
    assert _PLAN_LIMITS_MONTHLY["max"] == 82_000_000_000


@pytest.mark.unit
def test_zhipu_multipliers():
    p = ZhipuQuotaProvider({"enabled": True})
    mults = p.multipliers
    glm52 = [m for m in mults if m.model == "glm-5.2"]
    assert len(glm52) == 1
    assert glm52[0].peak == 3.0
    assert glm52[0].off_peak == 2.0


@pytest.mark.unit
def test_xiaomi_multipliers():
    p = XiaomiQuotaProvider({"enabled": True})
    mults = p.multipliers
    # Night-time coefficient should be 0.8 for off-peak
    assert any(m.off_peak == 0.8 for m in mults)


# ── Registry tests ──────────────────────────────────────────────


@pytest.mark.unit
def test_registry_has_providers():
    reg = get_registry()
    reg.reload()
    assert "zhipu" in reg.providers
    assert "xiaomi" in reg.providers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_api_empty(client):
    """GET /api/quota returns empty list when no providers are enabled."""
    # Ensure registry is fresh (nothing enabled in default config)
    get_registry().reload()
    res = await client.get("/api/quota")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert data["total"] >= 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_providers_api(client):
    """GET /api/quota/providers returns provider metadata."""
    get_registry().reload()
    res = await client.get("/api/quota/providers")
    assert res.status_code == 200
    providers = res.json()
    assert isinstance(providers, list)
    ids = {p["provider_id"] for p in providers}
    assert "zhipu" in ids
    assert "xiaomi" in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_config_update(client):
    """PUT /api/quota/config updates provider enabled state."""
    # Enable zhipu
    res = await client.put("/api/quota/config", json={
        "provider": "zhipu",
        "enabled": True,
        "plan_type": "pro",
    })
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Verify it's now enabled
    res = await client.get("/api/quota/providers")
    zhipu = next(p for p in res.json() if p["provider_id"] == "zhipu")
    assert zhipu["enabled"] is True

    # Clean up — disable it
    await client.put("/api/quota/config", json={"provider": "zhipu", "enabled": False})
