"""Tests for the Bailian (阿里云百炼) Token Plan quota provider.

团队版席位额度走纯 AK/SK 签名的官方 OpenAPI（GetSubscriptionSeatDetails），
无本地估算回退（没有 Credits 定价表），失败一律回 error 快照。
"""

import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from backend.quota.bailian import (
    BailianQuotaProvider,
    sign_headers,
)
from backend.quota.registry import get_registry

# ── Fixtures ────────────────────────────────────────────────────

# 真实响应形状（PascalCase），时间戳为 epoch 毫秒。
_SEAT_A = {
    "SeatId": "seat-001",
    "SpecType": "pro",
    "Status": "NORMAL",
    "AssignedStatus": "ASSIGNED",
    "AccountName": "张三",
    "AccountEmail": "zhangsan@example.com",
    "StartTime": 1767225600000,   # 2026-01-01T00:00:00Z
    "EndTime": 1798761600000,     # 2027-01-01T00:00:00Z
    "EquityList": [
        {
            "EquityType": "credits",
            "CycleInstanceId": "cycle-1",
            "CycleStartTime": 1767225600000,
            "CycleEndTime": 1769817600000,  # 2026-01-31T00:00:00Z
            "CycleTotalValue": 45000,
            "CycleSurplusValue": 40800,
        },
    ],
}
_SEAT_B = {
    "SeatId": "seat-002",
    "SpecType": "standard",
    "Status": "LIMIT",
    "AssignedStatus": "ASSIGNED",
    "AccountName": "李四",
    "StartTime": 1767225600000,
    "EndTime": 1798761600000,
    "EquityList": [
        {
            "EquityType": "credits",
            "CycleStartTime": 1767225600000,
            "CycleEndTime": 1769817600000,
            "CycleTotalValue": 20000,
            "CycleSurplusValue": 0,
        },
    ],
}


def _seat_response(items: list[dict], total: int | None = None) -> dict:
    return {
        "Success": True,
        "Data": {"Items": items, "Total": total if total is not None else len(items)},
    }


def _provider(**cfg) -> BailianQuotaProvider:
    base = {"enabled": True, "access_key_id": "LTAItest", "access_key_secret": "secret"}
    base.update(cfg)
    return BailianQuotaProvider(base)


# ── ACS3 签名 ───────────────────────────────────────────────────


@pytest.mark.unit
def test_sign_headers_structure():
    headers = sign_headers(
        method="GET",
        host="modelstudio.cn-beijing.aliyuncs.com",
        path="/tokenplan/subscription/seat-detail",
        query={"PageSize": "50", "PageNo": "1"},
        action="GetSubscriptionSeatDetails",
        version="2026-02-10",
        ak_id="LTAItest",
        ak_secret="secret",
        date="2026-11-27T00:00:00Z",
        nonce="fixednonce",
    )
    assert headers["x-acs-action"] == "GetSubscriptionSeatDetails"
    assert headers["x-acs-version"] == "2026-02-10"
    assert headers["x-acs-date"] == "2026-11-27T00:00:00Z"
    assert headers["x-acs-signature-nonce"] == "fixednonce"
    assert headers["x-acs-content-sha256"] == hashlib.sha256(b"").hexdigest()
    auth = headers["Authorization"]
    assert auth.startswith("ACS3-HMAC-SHA256 Credential=LTAItest,")
    assert "SignedHeaders=content-type;host;x-acs-action;x-acs-content-sha256;" \
           "x-acs-date;x-acs-signature-nonce;x-acs-version," in auth
    assert "Signature=" in auth


@pytest.mark.unit
def test_sign_headers_known_vector():
    """按阿里云 V3 签名规范独立重算期望签名，验证实现不是自说自话。"""
    host = "modelstudio.cn-beijing.aliyuncs.com"
    path = "/tokenplan/subscription/seat-detail"
    query = {"PageNo": "1", "PageSize": "50"}
    date = "2026-11-27T00:00:00Z"
    nonce = "fixednonce"
    hashed_body = hashlib.sha256(b"").hexdigest()

    signed = ["content-type", "host", "x-acs-action", "x-acs-content-sha256",
              "x-acs-date", "x-acs-signature-nonce", "x-acs-version"]
    header_values = {
        "content-type": "application/json",
        "host": host,
        "x-acs-action": "GetSubscriptionSeatDetails",
        "x-acs-content-sha256": hashed_body,
        "x-acs-date": date,
        "x-acs-signature-nonce": nonce,
        "x-acs-version": "2026-02-10",
    }
    canonical_headers = "".join(f"{k}:{header_values[k]}\n" for k in signed)
    canonical_request = "\n".join([
        "GET", path, "PageNo=1&PageSize=50",
        canonical_headers, ";".join(signed), hashed_body,
    ])
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(
        canonical_request.encode("utf-8")).hexdigest()
    expected = hmac.new(b"secret", string_to_sign.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    headers = sign_headers(
        method="GET", host=host, path=path, query=query,
        action="GetSubscriptionSeatDetails", version="2026-02-10",
        ak_id="LTAItest", ak_secret="secret", date=date, nonce=nonce,
    )
    assert headers["Authorization"].endswith(f"Signature={expected}")


@pytest.mark.unit
def test_sign_headers_query_encoding_and_order():
    """query 按 key 字典序、RFC3986 编码；空 query 规范化为空串。"""
    h1 = sign_headers(
        method="GET", host="h", path="/p", query={"B": "x y", "A": "1"},
        action="A", version="V", ak_id="id", ak_secret="s",
        date="2026-11-27T00:00:00Z", nonce="n",
    )
    h2 = sign_headers(
        method="GET", host="h", path="/p", query={"A": "1", "B": "x y"},
        action="A", version="V", ak_id="id", ak_secret="s",
        date="2026-11-27T00:00:00Z", nonce="n",
    )
    assert h1["Authorization"] == h2["Authorization"]  # 顺序无关
    h3 = sign_headers(
        method="GET", host="h", path="/p", query={},
        action="A", version="V", ak_id="id", ak_secret="s",
        date="2026-11-27T00:00:00Z", nonce="n",
    )
    assert h3["Authorization"] != h1["Authorization"]  # 空 query 参与签名


@pytest.mark.unit
def test_sign_headers_secret_changes_signature():
    kwargs = {"method": "GET", "host": "h", "path": "/p", "query": {}, "action": "A",
              "version": "V", "ak_id": "id", "date": "2026-11-27T00:00:00Z", "nonce": "n"}
    a = sign_headers(ak_secret="s1", **kwargs)
    b = sign_headers(ak_secret="s2", **kwargs)
    assert a["Authorization"] != b["Authorization"]


# ── 响应解析 ────────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_seats_multi_seat():
    p = _provider()
    snap = p._parse_seats([_SEAT_A, _SEAT_B])

    assert snap.provider == "bailian"
    assert snap.source == "api"
    assert snap.plan_type == "team"
    assert snap.plan_name == "团队版 · 2席位"

    # 主窗口 = 团队合计（reset_at 留空：各席位周期不同）
    assert snap.main_window is not None
    assert snap.main_window.label == "团队合计（2席位）"
    assert snap.main_window.total == 65000
    assert snap.main_window.used == pytest.approx(4200 + 20000)
    assert snap.main_window.unit == "credits"
    assert snap.main_window.reset_at is None

    # 每席位一个窗口
    assert len(snap.extra_windows) == 2
    wa, wb = snap.extra_windows
    assert wa.label == "张三 · Pro"
    assert wa.used == pytest.approx(4200)
    assert wa.total == 45000
    assert wa.reset_at == datetime.fromtimestamp(1769817600, tz=UTC).isoformat()
    assert wb.label == "李四 · Standard（限流）"
    assert wb.used == pytest.approx(20000)
    assert wb.ratio == 1.0

    # 订阅到期 = 各席位 EndTime 最大值
    assert snap.expires_at == datetime.fromtimestamp(1798761600, tz=UTC).isoformat()


@pytest.mark.unit
def test_parse_seats_equity_selection_and_fallbacks():
    """EquityList 取 CycleTotalValue 最大且 >0 的条目；缺成员名回退邮箱前缀。"""
    seat = {
        "SeatId": "seat-003",
        "SpecType": "max",
        "Status": "NORMAL",
        "AccountEmail": "wangwu@example.com",
        "EndTime": 1798761600000,
        "EquityList": [
            {"EquityType": "harness", "CycleTotalValue": 0, "CycleSurplusValue": 0},
            {"EquityType": "small", "CycleTotalValue": 100, "CycleSurplusValue": 50},
            {"EquityType": "credits", "CycleTotalValue": 90000,
             "CycleSurplusValue": 89000, "CycleEndTime": 1769817600000},
        ],
    }
    snap = _provider()._parse_seats([seat])
    w = snap.extra_windows[0]
    assert w.label == "wangwu · Max"
    assert w.total == 90000
    assert w.used == pytest.approx(1000)


@pytest.mark.unit
def test_parse_seats_no_equity_and_unassigned():
    seat = {"SeatId": "seat-004", "SpecType": "pro", "Status": "NORMAL",
            "AssignedStatus": "UNASSIGNED", "EquityList": []}
    snap = _provider()._parse_seats([seat])
    w = snap.extra_windows[0]
    assert "无额度数据" in w.label
    assert w.total == 0 and w.used == 0
    # 合计只统计有额度的席位，但席位计数含全部
    assert snap.main_window.total == 0
    assert snap.plan_name == "团队版 · 1席位"


@pytest.mark.unit
def test_parse_seats_seconds_timestamps():
    """防御：时间戳 <1e12 按秒处理。"""
    seat = dict(_SEAT_A, EndTime=1798761600,
                EquityList=[dict(_SEAT_A["EquityList"][0], CycleEndTime=1769817600)])
    snap = _provider()._parse_seats([seat])
    assert snap.extra_windows[0].reset_at == datetime.fromtimestamp(1769817600, tz=UTC).isoformat()
    assert snap.expires_at == datetime.fromtimestamp(1798761600, tz=UTC).isoformat()


@pytest.mark.unit
def test_parse_seats_surplus_over_total_clamped():
    seat = dict(_SEAT_A, EquityList=[
        dict(_SEAT_A["EquityList"][0], CycleSurplusValue=99999),
    ])
    snap = _provider()._parse_seats([seat])
    assert snap.extra_windows[0].used == 0


# ── fetch 路由与错误态 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_quota_no_credential():
    snap = await BailianQuotaProvider({"enabled": True}).fetch_quota()
    assert snap.source == "error"
    assert "AccessKey" in snap.error
    assert snap.main_window is None


@pytest.mark.asyncio
async def test_fetch_quota_partial_credential():
    snap = await BailianQuotaProvider(
        {"enabled": True, "access_key_id": "LTAItest"}).fetch_quota()
    assert snap.source == "error"


@pytest.mark.asyncio
async def test_fetch_quota_success():
    p = _provider()
    with patch.object(BailianQuotaProvider, "_http_get_signed",
                      AsyncMock(return_value=_seat_response([_SEAT_A, _SEAT_B]))):
        snap = await p.fetch_quota()
    assert snap.source == "api"
    assert snap.error is None
    assert len(snap.extra_windows) == 2


@pytest.mark.asyncio
async def test_fetch_quota_pagination():
    p = _provider()
    page1 = _seat_response([_SEAT_A], total=2)
    page2 = _seat_response([_SEAT_B], total=2)
    mock = AsyncMock(side_effect=[page1, page2])
    with patch.object(BailianQuotaProvider, "_http_get_signed", mock):
        snap = await p.fetch_quota()
    assert mock.await_count == 2
    assert len(snap.extra_windows) == 2
    # 第二页 PageNo=2
    assert mock.await_args_list[1].kwargs["query"]["PageNo"] == "2"


@pytest.mark.asyncio
async def test_fetch_quota_http_error_maps_friendly():
    p = _provider()
    with patch.object(BailianQuotaProvider, "_http_get_signed",
                      AsyncMock(side_effect=RuntimeError(
                          "SignatureDoesNotMatch: Specified signature is not matched"))):
        snap = await p.fetch_quota()
    assert snap.source == "error"
    assert "Secret" in snap.error
    assert snap.main_window is None


@pytest.mark.asyncio
async def test_fetch_quota_empty_seats():
    p = _provider()
    with patch.object(BailianQuotaProvider, "_http_get_signed",
                      AsyncMock(return_value=_seat_response([]))):
        snap = await p.fetch_quota()
    assert snap.source == "error"
    assert "席位" in snap.error


@pytest.mark.asyncio
async def test_fetch_quota_business_failure():
    p = _provider()
    with patch.object(BailianQuotaProvider, "_http_get_signed",
                      AsyncMock(side_effect=RuntimeError("Forbidden.RAM: no permission"))):
        snap = await p.fetch_quota()
    assert snap.source == "error"
    assert "权限" in snap.error


@pytest.mark.unit
def test_credential_property_requires_both():
    assert _provider().credential != ""
    assert BailianQuotaProvider({"access_key_id": "x"}).credential == ""
    assert BailianQuotaProvider({"access_key_secret": "y"}).credential == ""


# ── Registry / Config API integration ───────────────────────────


@pytest.mark.unit
def test_registry_has_bailian():
    reg = get_registry()
    reg.reload()
    assert "bailian" in reg.providers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bailian_config_persist(client, tmp_path, monkeypatch):
    """PUT 保存 AK 字段：持久化、has_access_key、绝不回显凭据。"""
    from backend.api import quota as quota_api
    from backend.quota import registry as registry_module

    cfg = tmp_path / "quota_providers.yaml"
    monkeypatch.setattr(quota_api, "_CONFIG_YAML", cfg)
    monkeypatch.setattr(registry_module, "_CONFIG_YAML", cfg)
    get_registry().reload()

    res = await client.put("/api/quota/config", json={
        "provider": "bailian",
        "enabled": True,
        "access_key_id": "LTAItest",
        "access_key_secret": "supersecret",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["config"]["has_access_key"] is True
    assert "supersecret" not in res.text
    assert "LTAItest" not in res.text

    # YAML 落盘
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert raw["providers"]["bailian"]["access_key_id"] == "LTAItest"
    assert raw["providers"]["bailian"]["access_key_secret"] == "supersecret"

    # providers 元数据：has_credential 生效
    res = await client.get("/api/quota/providers")
    bailian = next(p for p in res.json() if p["provider_id"] == "bailian")
    assert bailian["enabled"] is True
    assert bailian["has_credential"] is True

    # 空串清除
    res = await client.put("/api/quota/config", json={
        "provider": "bailian", "access_key_id": "", "access_key_secret": "",
    })
    assert res.json()["config"]["has_access_key"] is False

    # 清理：禁用，避免影响其他用例
    await client.put("/api/quota/config", json={"provider": "bailian", "enabled": False})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bailian_snapshot_serializes_label(client, tmp_path, monkeypatch):
    """GET /api/quota 的窗口序列化包含 label 字段。"""
    from backend.api import quota as quota_api
    from backend.quota import registry as registry_module

    cfg = tmp_path / "quota_providers.yaml"
    cfg.write_text(yaml.dump({"providers": {"bailian": {
        "enabled": True, "access_key_id": "LTAItest", "access_key_secret": "s",
    }}}), encoding="utf-8")
    monkeypatch.setattr(quota_api, "_CONFIG_YAML", cfg)
    monkeypatch.setattr(registry_module, "_CONFIG_YAML", cfg)
    get_registry().reload()

    with patch.object(BailianQuotaProvider, "_http_get_signed",
                      AsyncMock(return_value=_seat_response([_SEAT_A]))):
        res = await client.get("/api/quota")
    assert res.status_code == 200
    items = res.json()["items"]
    snap = next(s for s in items if s["provider"] == "bailian")
    assert snap["main_window"]["label"] == "团队合计（1席位）"
    assert snap["extra_windows"][0]["label"] == "张三 · Pro"