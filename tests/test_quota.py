"""Tests for the quota monitoring module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.db import database as db_module
from backend.db.models import TokenRecord, insert_records
from backend.quota import multipliers as mult_module
from backend.quota.base import QuotaSnapshot, QuotaWindow
from backend.quota.registry import get_registry
from backend.quota.xiaomi import XiaomiQuotaProvider, _plan_limits_monthly
from backend.quota.zhipu import ZhipuQuotaProvider

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
    credits = mult_module.get_plan_limits("zhipu", "credits")
    assert credits["lite"]["window_5h"] == 2000
    assert credits["pro"]["weekly"] == 60000
    assert credits["max"]["weekly"] == 140000
    prompts = mult_module.get_plan_limits("zhipu", "prompts")
    assert prompts["lite"]["window_5h"] == 80
    assert prompts["pro"]["weekly"] == 2000
    assert prompts["max"]["window_5h"] == 1600


@pytest.mark.unit
def test_xiaomi_plan_limits():
    limits = _plan_limits_monthly()
    assert limits["lite"] == 4_100_000_000
    assert limits["max"] == 82_000_000_000


@pytest.mark.unit
def test_zhipu_multipliers():
    p = ZhipuQuotaProvider({"enabled": True})
    mults = p.multipliers
    glm54 = [m for m in mults if m.model == "glm-5.4"]
    assert len(glm54) == 1
    # 当前积分制：Input 抵扣系数 4.6，非高峰 5 折
    assert glm54[0].input_rate == 4.6
    assert glm54[0].output_rate == 16.0
    assert glm54[0].off_peak == 0.5


# ── Zhipu API-key path (Coding Plan usage endpoint) ─────────────


def _zhipu_pro() -> ZhipuQuotaProvider:
    return ZhipuQuotaProvider({"enabled": True, "plan_type": "pro", "session_token": "x"})


def _coding_plan_body(limits: list[dict], level: str = "PRO",
                      success: bool = True, msg: str = "") -> dict:
    return {"success": success, "msg": msg, "data": {"level": level, "limits": limits}}


@pytest.mark.unit
def test_is_api_key_detection():
    assert ZhipuQuotaProvider._is_api_key("863c9913abcdef0123456789abcdef.EwZS7q3hfZWORguU")
    assert not ZhipuQuotaProvider._is_api_key("t" * 120)          # long → session token
    assert not ZhipuQuotaProvider._is_api_key("userId=1; token=abc")  # cookie-like
    assert not ZhipuQuotaProvider._is_api_key("short.abc")        # first part ≤ 10 chars


@pytest.mark.unit
def test_parse_coding_plan_dual_windows():
    """unit=3 → 5h window, unit=6 → weekly; used back-computed from plan limits."""
    p = _zhipu_pro()
    body = _coding_plan_body([
        {"type": "TOKENS_LIMIT", "unit": 3, "number": 5,
         "percentage": 42.5, "nextResetTime": 1748000000000},
        {"type": "TOKENS_LIMIT", "unit": 6, "number": 7,
         "percentage": 12.5, "nextResetTime": 1748600000000},
    ], level="PRO")

    snap = p._parse_coding_plan_response(body)

    assert snap is not None and snap.source == "api"
    assert snap.plan_type == "pro" and snap.plan_name == "Pro"
    assert snap.main_window is not None
    assert snap.main_window.total == 400.0          # pro 5h limit
    assert snap.main_window.used == 170.0           # 400 × 42.5%
    assert snap.main_window.ratio == pytest.approx(0.425)
    assert snap.main_window.reset_at == datetime.fromtimestamp(1748000000, tz=UTC).isoformat()
    assert len(snap.extra_windows) == 1
    assert snap.extra_windows[0].total == 2000.0    # pro weekly limit
    assert snap.extra_windows[0].used == 250.0      # 2000 × 12.5%


@pytest.mark.unit
def test_parse_coding_plan_weekly_resetting_earlier():
    """cc-switch #3036: near a cycle's end the weekly window resets EARLIER
    than the 5h one — reset-time ordering would swap the buckets; the
    explicit ``unit`` field must win."""
    p = _zhipu_pro()
    body = _coding_plan_body([
        {"type": "TOKENS_LIMIT", "unit": 3, "percentage": 50.0, "nextResetTime": 2000000000000},
        {"type": "TOKENS_LIMIT", "unit": 6, "percentage": 80.0, "nextResetTime": 1000000000000},
    ])

    snap = p._parse_coding_plan_response(body)

    assert snap is not None
    assert snap.main_window.used == 200.0           # 50% of 400, not 80%
    assert snap.extra_windows[0].used == 1600.0      # 80% of 2000


@pytest.mark.unit
def test_parse_coding_plan_unit_missing_fallback():
    """Fallback heuristic: no-reset entry → 5h slot, reset entries fill by time."""
    p = _zhipu_pro()
    body = _coding_plan_body([
        {"type": "TOKENS_LIMIT", "percentage": 10.0},                        # no reset → 5h
        {"type": "TOKENS_LIMIT", "percentage": 30.0, "nextResetTime": 999},  # → weekly
    ])

    snap = p._parse_coding_plan_response(body)

    assert snap is not None
    assert snap.main_window is not None and snap.main_window.used == 40.0
    assert len(snap.extra_windows) == 1 and snap.extra_windows[0].used == 600.0


@pytest.mark.unit
def test_parse_coding_plan_legacy_single_window():
    """Legacy plans return a single limit — weekly window simply absent."""
    p = _zhipu_pro()
    snap = p._parse_coding_plan_response(
        _coding_plan_body([{"type": "TOKENS_LIMIT", "percentage": 5.0}])
    )
    assert snap is not None
    assert snap.main_window is not None and snap.main_window.used == 20.0
    assert snap.extra_windows == []


@pytest.mark.unit
def test_parse_coding_plan_level_and_filters():
    p = _zhipu_pro()
    # Unknown level → keep user-configured plan_type
    snap = p._parse_coding_plan_response(
        _coding_plan_body([{"type": "TOKENS_LIMIT", "unit": 3, "percentage": 0.0}],
                          level="ULTRA")
    )
    assert snap is not None and snap.plan_type == "pro"
    assert snap.main_window.unit == "prompts"          # TOKENS_LIMIT → 历史 V2 制式
    # CREDIT_LIMIT accepted case-insensitively → 积分制额度; unknown types ignored
    snap = p._parse_coding_plan_response(_coding_plan_body([
        {"type": "credit_limit", "unit": 3, "percentage": 25.0},
        {"type": "SOMETHING_ELSE", "unit": 6, "percentage": 99.0},
    ], level="lite"))
    assert snap is not None
    assert snap.plan_type == "lite" and snap.main_window.total == 2000.0
    assert snap.main_window.unit == "credits"          # CREDIT_LIMIT → 积分制
    assert snap.extra_windows == []  # SOMETHING_ELSE filtered out


@pytest.mark.unit
def test_parse_coding_plan_error_shapes():
    p = _zhipu_pro()
    assert p._parse_coding_plan_response({"success": False, "msg": "boom"}) is None
    assert p._parse_coding_plan_response({"success": True}) is None          # no data
    assert p._parse_coding_plan_response("not-a-dict") is None               # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_fetch_via_api_key_success():
    p = _zhipu_pro()
    body = _coding_plan_body([{"type": "TOKENS_LIMIT", "unit": 3, "percentage": 10.0}])
    with patch.object(ZhipuQuotaProvider, "_http_get", AsyncMock(return_value=body)):
        snap = await p._fetch_via_api_key("fake" * 8 + ".key")
    assert snap.source == "api"
    assert snap.error is None


@pytest.mark.asyncio
async def test_fetch_via_api_key_falls_back_on_http_error():
    p = _zhipu_pro()
    estimate = QuotaSnapshot(provider="zhipu", display_name="x", plan_name="Pro",
                             source="estimate")
    with (
        patch.object(ZhipuQuotaProvider, "_http_get",
                     AsyncMock(side_effect=OSError("HTTP Error 401"))),
        patch.object(ZhipuQuotaProvider, "_estimate", AsyncMock(return_value=estimate)),
    ):
        snap = await p._fetch_via_api_key("fake" * 8 + ".key")
    assert snap.source == "estimate"
    assert snap.error and "401" in snap.error


@pytest.mark.asyncio
async def test_fetch_via_api_key_falls_back_on_unparseable_body():
    p = _zhipu_pro()
    estimate = QuotaSnapshot(provider="zhipu", display_name="x", plan_name="Pro",
                             source="estimate")
    with (
        patch.object(ZhipuQuotaProvider, "_http_get", AsyncMock(return_value={"success": False})),
        patch.object(ZhipuQuotaProvider, "_estimate", AsyncMock(return_value=estimate)),
    ):
        snap = await p._fetch_via_api_key("fake" * 8 + ".key")
    assert snap.source == "estimate"
    assert snap.error is not None


@pytest.mark.asyncio
async def test_fetch_quota_routes_credential_types():
    """API-key-shaped credential → coding-plan path; session token → web path."""
    api_snapshot = QuotaSnapshot(provider="zhipu", display_name="x", plan_name="Pro")
    web_snapshot = QuotaSnapshot(provider="zhipu", display_name="x", plan_name="Pro")

    p_key = ZhipuQuotaProvider(
        {"enabled": True, "plan_type": "pro",
         "session_token": "a" * 32 + "." + "b" * 16}  # xxx.yyy API-key format
    )
    with patch.object(ZhipuQuotaProvider, "_fetch_via_api_key",
                      AsyncMock(return_value=api_snapshot)) as m_key:
        assert (await p_key.fetch_quota()) is api_snapshot
    m_key.assert_awaited_once()

    p_sess = ZhipuQuotaProvider(
        {"enabled": True, "plan_type": "pro",
         "session_token": "t" * 120 + "=1"}  # long, cookie-like → session token
    )
    with patch.object(ZhipuQuotaProvider, "_fetch_api",
                      AsyncMock(return_value=web_snapshot)) as m_web:
        assert (await p_sess.fetch_quota()) is web_snapshot
    m_web.assert_awaited_once()


@pytest.mark.unit
def test_xiaomi_multipliers():
    p = XiaomiQuotaProvider({"enabled": True})
    mults = p.multipliers
    names = {m.model for m in mults}
    # mimo-v2.5 系列已于 2026-10-21 下线，卡片应展示 V2.6 系列
    assert {"mimo-v2.6-pro", "mimo-v2.6-flash", "mimo-v2.6-pro-ultraspeed"} <= names
    # Night-time coefficient should be 0.8 for off-peak
    assert any(m.off_peak == 0.8 for m in mults)
    assert any(m.input_rate == 300.0 for m in mults if m.model == "mimo-v2.6-pro")


# ── Local estimates (no credential / API failure fallback) ──────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_xiaomi_estimate_sums_increment_rows(client):
    """估算按行直接求和。入库的行已是统一口径——``input_tokens`` 为未命中输入、
    每行是真实增量——归一工作由采集器和 user_version=2 迁移完成。"""
    now = datetime.now(UTC)
    db = await db_module.get_db()
    await insert_records(db, [
        # Hermes：会话关闭后的一行总量 + 另一会话的小时增量
        TokenRecord(timestamp=now.isoformat(), agent="hermes-win", model="mimo-v2.6-pro",
                    session_id="A", input_tokens=1000, output_tokens=100, cache_read_tokens=5000),
        TokenRecord(timestamp=(now - timedelta(hours=1)).isoformat(), agent="hermes-win",
                    model="mimo-v2.6-pro", session_id="B",
                    input_tokens=2000, output_tokens=300, cache_read_tokens=9000),
        # zcode：入库时已换算成未命中输入
        TokenRecord(timestamp=now.isoformat(), agent="zcode", model="mimo-v2.6-pro",
                    input_tokens=500, output_tokens=50, cache_read_tokens=4000),
    ])
    snap = await XiaomiQuotaProvider({"enabled": True, "plan_type": "pro"})._estimate()
    # 1000×300 + 5000×2.5 + 100×600 = 372,500
    # 2000×300 + 9000×2.5 + 300×600 = 802,500
    #  500×300 + 4000×2.5 +  50×600 = 190,000
    assert snap.main_window.used == pytest.approx(1_365_000.0)
    assert snap.main_window.total == 38_000_000_000.0
    assert snap.main_window.unit == "credits"
    assert snap.source == "estimate"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zhipu_credit_estimate_formula(client):
    """积分制估算 =（未命中输入×Input + 缓存命中×Cached + 输出×Output）/ 10000，
    5 小时与周窗口各算一次，openrouter 行不计入。"""
    now = datetime.now(UTC)
    db = await db_module.get_db()
    await insert_records(db, [
        TokenRecord(timestamp=now.isoformat(), agent="hermes-win", model="glm-5.4",
                    session_id="A", input_tokens=1000, output_tokens=100, cache_read_tokens=5000),
        TokenRecord(timestamp=(now - timedelta(hours=1)).isoformat(), agent="zcode",
                    model="glm-5.3", input_tokens=2000, output_tokens=100, cache_read_tokens=5000),
        TokenRecord(timestamp=now.isoformat(), agent="openrouter", model="glm-5.4",
                    input_tokens=999_999, output_tokens=1, cache_read_tokens=1),
    ])
    p = ZhipuQuotaProvider({"enabled": True, "plan_type": "pro"})
    assert p.mode == "credits"
    snap = await p._estimate()
    # hermes-win glm-5.4: (1000×4.6 + 5000×1.1 + 100×16) / 10000 = 1.17
    # zcode      glm-5.3: (2000×6.9 + 5000×1.7 + 100×24) / 10000 = 2.47
    assert snap.main_window.used == pytest.approx(3.64)
    assert snap.extra_windows[0].used == pytest.approx(3.64)
    assert snap.main_window.total == 12_000.0
    assert snap.main_window.unit == "credits"
    assert snap.source == "estimate"


# ── Registry tests ──────────────────────────────────────────────


@pytest.mark.unit
def test_registry_has_providers():
    reg = get_registry()
    reg.reload()
    assert "zhipu" in reg.providers
    assert "xiaomi" in reg.providers
    assert "bailian" in reg.providers


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
    assert "bailian" in ids


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
