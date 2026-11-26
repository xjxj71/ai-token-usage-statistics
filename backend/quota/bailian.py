"""阿里云百炼 Token Plan（团队版）quota provider.

团队版席位额度走纯 AK/SK 签名的官方 OpenAPI（ACS3-HMAC-SHA256，阿里云 V3
签名），无需控制台登录态：

    GET https://modelstudio.cn-beijing.aliyuncs.com/tokenplan/subscription/seat-detail
    Action: GetSubscriptionSeatDetails   Version: 2026-02-10

AccessKey 由管理员在主账号下创建 RAM 只读子用户生成，一次配置长期可用。
每个席位返回当前计量周期的总额度 / 剩余额度 / 周期起止（重置时间）。

与其他 provider 不同，这里**没有本地估算回退**：百炼以 Credits 计量且
各模型单价不同，本地没有可靠的 Credits 定价表，失败一律回 error 快照。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.quota.base import QuotaProvider, QuotaSnapshot, QuotaWindow

logger = logging.getLogger(__name__)

_HOSTS = {
    "cn-beijing": "modelstudio.cn-beijing.aliyuncs.com",
    "ap-southeast-1": "modelstudio.ap-southeast-1.aliyuncs.com",
}
_API_VERSION = "2026-02-10"
_SEAT_ACTION = "GetSubscriptionSeatDetails"
_SEAT_PATH = "/tokenplan/subscription/seat-detail"
_PAGE_SIZE = 50
_MAX_PAGES = 10

# 非 NORMAL 席位状态的中文后缀（NORMAL 不加后缀）。
_STATUS_SUFFIX = {
    "LIMIT": "（限流）",
    "STOP": "（停用）",
    "RELEASE": "（已释放）",
    "REFUNDED": "（已退款）",
    "CREATING": "（创建中）",
}


# ── ACS3-HMAC-SHA256 签名（阿里云 OpenAPI V3）─────────────────────


def _rfc3986(value: str) -> str:
    return urllib.parse.quote(str(value), safe="-_.~")


def sign_headers(
    *,
    method: str,
    host: str,
    path: str,
    query: dict[str, str],
    action: str,
    version: str,
    ak_id: str,
    ak_secret: str,
    body: bytes = b"",
    date: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """构造带 ACS3 签名的请求头。date/nonce 可注入以便单测。"""
    date = date or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = nonce or uuid.uuid4().hex
    hashed_body = hashlib.sha256(body).hexdigest()

    headers = {
        "content-type": "application/json",
        "host": host,
        "x-acs-action": action,
        "x-acs-content-sha256": hashed_body,
        "x-acs-date": date,
        "x-acs-signature-nonce": nonce,
        "x-acs-version": version,
    }
    signed_keys = sorted(headers)
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed_keys)
    signed_headers_str = ";".join(signed_keys)
    canonical_query = "&".join(
        f"{_rfc3986(k)}={_rfc3986(v)}" for k, v in sorted(query.items())
    )
    # canonical_headers 自带末尾换行，与规范中的空行分隔一致
    canonical_request = (
        f"{method.upper()}\n{path}\n{canonical_query}\n"
        f"{canonical_headers}\n{signed_headers_str}\n{hashed_body}"
    )
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(
        canonical_request.encode("utf-8")).hexdigest()
    signature = hmac.new(
        ak_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    out = dict(headers)
    out["Authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={ak_id},"
        f"SignedHeaders={signed_headers_str},Signature={signature}"
    )
    out["Accept"] = "application/json"
    out["User-Agent"] = "ai-token-usage/1.0"
    return out


# ── 解析辅助 ────────────────────────────────────────────────────


def _ts_to_iso(value: Any) -> str | None:
    """epoch 毫秒 → ISO-8601；<1e12 防御性按秒处理。"""
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    if ts >= 1e12:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _pick_equity(equity_list: list[dict]) -> dict | None:
    """取 CycleTotalValue 最大且 >0 的权益条目作为额度周期。"""
    best: dict | None = None
    best_total = 0.0
    for equity in equity_list:
        try:
            total = float(equity.get("CycleTotalValue") or 0)
        except (TypeError, ValueError):
            continue
        if total > best_total:
            best, best_total = equity, total
    return best


def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    known = (
        ("InvalidAccessKeyId.NotFound", "AccessKey ID 不存在或已禁用"),
        ("SignatureDoesNotMatch", "AccessKey Secret 错误（签名不匹配）"),
        ("Forbidden.RAM", "RAM 用户缺少调用权限，请授予百炼只读权限"),
        ("NoPermission", "RAM 用户缺少调用权限，请授予百炼只读权限"),
    )
    for code, zh in known:
        if code in msg:
            return f"{zh} [{code}]"
    if "Forbidden" in msg:
        return f"RAM 用户缺少调用权限，请授予百炼只读权限 [{msg[:120]}]"
    return msg[:300]


class BailianQuotaProvider(QuotaProvider):
    provider_id = "bailian"
    display_name = "阿里云百炼 Token Plan"

    @property
    def credential(self) -> str:
        """ID + Secret 齐全才算有凭据（供 has_credential 展示）。"""
        if self.config.get("access_key_id") and self.config.get("access_key_secret"):
            return self.config["access_key_secret"]
        return ""

    @property
    def region(self) -> str:
        return self.config.get("region") or "cn-beijing"

    async def fetch_quota(self) -> QuotaSnapshot:
        if not self.credential:
            return self._error_snapshot(
                "未配置 AccessKey，请在设置中填写管理员提供的阿里云 AK/SK"
            )
        try:
            return await self._fetch_api()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bailian API fetch failed: %s", exc)
            return self._error_snapshot(_friendly_error(exc))

    # ── API path ───────────────────────────────────────────────

    async def _fetch_api(self) -> QuotaSnapshot:
        ak_id = self.config.get("access_key_id", "")
        ak_secret = self.config.get("access_key_secret", "")
        host = _HOSTS.get(self.region, _HOSTS["cn-beijing"])

        items: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            body = await self._http_get_signed(
                host=host,
                path=_SEAT_PATH,
                query={"PageNo": str(page), "PageSize": str(_PAGE_SIZE)},
                action=_SEAT_ACTION,
                ak_id=ak_id,
                ak_secret=ak_secret,
            )
            data = body.get("Data") or {}
            page_items = data.get("Items") or []
            items.extend(page_items)
            total = data.get("Total")
            if not page_items or (
                isinstance(total, (int, float)) and len(items) >= total
            ):
                break

        if not items:
            raise RuntimeError(
                "未查询到团队版席位（账号未订阅团队版，或 AK 不属于该主账号）"
            )
        return self._parse_seats(items)

    def _parse_seats(self, items: list[dict]) -> QuotaSnapshot:
        windows: list[QuotaWindow] = []
        agg_used = agg_total = 0.0
        expiry_ts: list[float] = []

        for seat in items:
            name = (
                seat.get("AccountName")
                or (seat.get("AccountEmail") or "").split("@")[0]
                or seat.get("SeatId")
                or "席位"
            )
            spec = (seat.get("SpecType") or "").capitalize()
            label = f"{name} · {spec}" if spec else str(name)
            label += _STATUS_SUFFIX.get((seat.get("Status") or "").upper(), "")

            equity = _pick_equity(seat.get("EquityList") or [])
            if equity is None:
                windows.append(QuotaWindow(
                    used=0, total=0, unit="credits", label=label + "（无额度数据）",
                ))
            else:
                total = float(equity.get("CycleTotalValue") or 0)
                surplus = float(equity.get("CycleSurplusValue") or 0)
                used = max(0.0, total - surplus)
                windows.append(QuotaWindow(
                    used=used, total=total, unit="credits",
                    reset_at=_ts_to_iso(equity.get("CycleEndTime")), label=label,
                ))
                agg_used += used
                agg_total += total

            end = seat.get("EndTime")
            if end:
                try:
                    expiry_ts.append(float(end))
                except (TypeError, ValueError):
                    pass

        n = len(items)
        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=f"团队版 · {n}席位",
            plan_type="team",
            main_window=QuotaWindow(
                used=agg_used, total=agg_total, unit="credits",
                label=f"团队合计（{n}席位）",
            ),
            extra_windows=windows,
            expires_at=_ts_to_iso(max(expiry_ts)) if expiry_ts else None,
            fetched_at=datetime.now(UTC).isoformat(),
            source="api",
        )

    def _error_snapshot(self, message: str) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name="团队版",
            plan_type="team",
            fetched_at=datetime.now(UTC).isoformat(),
            source="error",
            error=message,
        )

    # ── HTTP helper ────────────────────────────────────────────

    @staticmethod
    async def _http_get_signed(
        *,
        host: str,
        path: str,
        query: dict[str, str],
        action: str,
        ak_id: str,
        ak_secret: str,
    ) -> dict:
        def _do() -> dict:
            headers = sign_headers(
                method="GET", host=host, path=path, query=query,
                action=action, version=_API_VERSION,
                ak_id=ak_id, ak_secret=ak_secret,
            )
            qs = urllib.parse.urlencode(query)
            url = f"https://{host}{path}" + (f"?{qs}" if qs else "")
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                code, msg = "", detail[:200]
                try:
                    err = json.loads(detail)
                    code = err.get("Code") or ""
                    msg = err.get("Message") or msg
                except Exception:  # noqa: BLE001
                    logger.debug("Unparseable API error body: %s", detail[:200])
                raise RuntimeError(
                    f"{code}: {msg}" if code else f"HTTP {exc.code}: {msg}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"网络错误: {exc.reason}") from exc
            if body.get("Success") is False:
                raise RuntimeError(
                    f"{body.get('Code', '')}: {body.get('Message', '接口返回失败')}"
                )
            return body

        return await asyncio.to_thread(_do)