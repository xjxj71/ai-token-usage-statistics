"""Xiaomi MiMo Token Plan quota provider.

The Xiaomi MiMo open platform (platform.xiaomimimo.com) authenticates
console APIs via Xiaomi SSO cookies — there is no API-key endpoint for
subscription balance.

When a valid ``cookie`` string is supplied (copied from the browser after
logging into platform.xiaomimimo.com), we call:

    GET /api/v1/tokenPlan/detail       — plan details (name, code, expiry)
    GET /api/v1/tokenPlan/usage        — Credits usage (used / limit / percent)
    GET /api/v1/userProfile            — account info

Otherwise we fall back to a local estimate computed from the
``token_usage`` table.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from backend.db import database as db_module
from backend.db.models import window_usage_rows
from backend.quota import multipliers as mult_module
from backend.quota.base import (
    ModelMultiplier,
    QuotaProvider,
    QuotaSnapshot,
    QuotaWindow,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://platform.xiaomimimo.com"

# 旧模型名 → 现行 V2.6 模型名（mimo-v2.5 系列已于 2026-10-21 下线）。
# 历史 token_usage 行仍可能带旧名，本地估算按现行倍率折算。
_MODEL_ALIASES: dict[str, str] = {
    "mimo-v2.5-pro": "mimo-v2.6-pro",
    "mimo-v2.5": "mimo-v2.6-flash",
    "mimo-v2-pro": "mimo-v2.6-pro",
    "mimo-v2": "mimo-v2.6-flash",
}


def _plan_limits_monthly() -> dict[str, float]:
    """Monthly Credit totals per plan type (from the fetched docs)."""
    limits = mult_module.get_plan_limits("xiaomi", "credits")
    return {plan: windows.get("monthly", 0.0) for plan, windows in limits.items()}


def _token_rates() -> dict[tuple[str, str], float]:
    """Per-token Credit deduction rates for local estimation.

    key: (model, token_type) -> credits_per_token, built from the fetched
    MiMo Token Plan table（输入/缓存/输出），含旧模型名别名。
    """
    rates: dict[tuple[str, str], float] = {}
    for m in mult_module.get_set("xiaomi", "credits").models:
        if m.input_rate is None:
            continue
        names = [m.model] + [a for a, t in _MODEL_ALIASES.items() if t == m.model]
        for name in names:
            rates[(name, "input_cache")] = m.cached_rate or 0.0
            rates[(name, "input_miss")] = m.input_rate
            rates[(name, "output")] = m.output_rate or 0.0
    return rates


class XiaomiQuotaProvider(QuotaProvider):
    provider_id = "xiaomi"
    display_name = "小米 MiMo Token Plan"

    @property
    def plan_type(self) -> str:
        return self.config.get("plan_type", "pro")

    @property
    def multipliers(self) -> list[ModelMultiplier]:
        return list(mult_module.get_set(self.provider_id, "credits").models)

    async def fetch_quota(self) -> QuotaSnapshot:
        cookie = self.credential
        if cookie:
            try:
                return await self._fetch_api(cookie)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Xiaomi API fetch failed, falling back to estimate: %s", exc)
                snapshot = await self._estimate()
                snapshot.error = str(exc)
                return snapshot
        return await self._estimate()

    # ── API path ───────────────────────────────────────────────

    async def _fetch_api(self, cookie: str) -> QuotaSnapshot:
        headers = {
            "Cookie": cookie,
            "Accept": "application/json",
            "User-Agent": "ai-token-usage/1.0",
        }

        plan_detail = await self._http_get(
            f"{_BASE_URL}/api/v1/tokenPlan/detail", headers
        )
        usage = await self._http_get(
            f"{_BASE_URL}/api/v1/tokenPlan/usage", headers
        )

        return self._parse_api_response(plan_detail, usage)

    def _parse_api_response(
        self,
        plan_data: dict,
        usage_data: dict,
    ) -> QuotaSnapshot:
        now_iso = datetime.now(UTC).isoformat()

        # --- Plan detail ---
        # Real response: {"code":0,"data":{"planCode":"standard","planName":"Standard",
        #   "currentPeriodEnd":"2026-07-27 23:59:59","enableAutoRenew":false,"expired":false}}
        plan_name = "Unknown"
        plan_type = self.plan_type
        expires_at: str | None = None
        auto_renew: bool | None = None

        p_data = plan_data.get("data") or {}
        if p_data:
            plan_name = p_data.get("planName") or p_data.get("plan_name", "Unknown")
            raw_type = (p_data.get("planCode") or p_data.get("planCode") or "").lower()
            if raw_type in _plan_limits_monthly():
                plan_type = raw_type
            expires_at = p_data.get("currentPeriodEnd") or p_data.get("expireTime")
            auto_renew = p_data.get("enableAutoRenew")

        # --- Usage ---
        # Real response: {"code":0,"data":{
        #   "usage":{"items":[
        #     {"limit":11000000000,"name":"plan_total_token","percent":0.04,"used":428118424},
        #     {"limit":0,"name":"compensation_total_token","percent":0,"used":0}
        #   ],"percent":0.04},
        #   "monthUsage":{"items":[...],"percent":0.0389}
        # }}
        used_credits: float = 0.0
        total_credits: float = float(_plan_limits_monthly().get(plan_type, 0))

        u_data = usage_data.get("data") or {}
        usage_block = u_data.get("usage") or {}
        items = usage_block.get("items") or []
        for item in items:
            name = item.get("name", "")
            if name == "plan_total_token":
                used_credits = float(item.get("used", 0))
                limit = item.get("limit", 0)
                if limit and limit > 0:
                    total_credits = float(limit)

        main_window = QuotaWindow(
            used=used_credits,
            total=total_credits,
            unit="credits",
            reset_at=expires_at,
        )

        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=plan_name,
            plan_type=plan_type,
            main_window=main_window,
            expires_at=expires_at,
            auto_renew=auto_renew,
            fetched_at=now_iso,
            source="api",
            **mult_module.snapshot_kwargs(self.provider_id, "credits"),
        )

    # ── HTTP helper ────────────────────────────────────────────

    @staticmethod
    async def _http_get(url: str, headers: dict[str, str]) -> dict:
        def _do() -> dict:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return await asyncio.to_thread(_do)

    # ── Local estimate fallback ────────────────────────────────

    async def _estimate(self) -> QuotaSnapshot:
        """Estimate Credits consumption from local ``token_usage`` table."""
        now_iso = datetime.now(UTC).isoformat()
        limits = _plan_limits_monthly()
        total_credits = float(limits.get(self.plan_type) or limits.get("pro") or 0)
        token_rates = _token_rates()

        try:
            db = await db_module.get_db()
            # Current billing period: last 30 days (simplified).
            period_start = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            rows = await window_usage_rows(db, "mimo-%", period_start)

            used_credits = 0.0
            for row in rows:
                model = (row["model"] or "").lower()
                # window_usage_rows 已把各采集器的入库口径统一为
                # 「未命中输入 / 缓存读取 / 缓存写入 / 输出」在窗口内的真实增量。
                rate_cache = token_rates.get((model, "input_cache"), 0)
                rate_miss = token_rates.get((model, "input_miss"), 0)
                rate_out = token_rates.get((model, "output"), 0)

                used_credits += (
                    row["cache_read"] * rate_cache
                    + row["input"] * rate_miss
                    + row["cache_write"] * rate_miss  # cache writes count as input
                    + row["output"] * rate_out
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Xiaomi local estimate failed: %s", exc)
            used_credits = 0.0

        main_window = QuotaWindow(
            used=used_credits,
            total=total_credits,
            unit="credits",
        )

        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=self.plan_type.capitalize(),
            plan_type=self.plan_type,
            main_window=main_window,
            fetched_at=now_iso,
            source="estimate",
            **mult_module.snapshot_kwargs(self.provider_id, "credits"),
        )
