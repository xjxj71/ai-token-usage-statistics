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
from datetime import datetime, timezone, timedelta
from typing import Any

from backend.db import database as db_module
from backend.quota.base import (
    ModelMultiplier,
    QuotaProvider,
    QuotaSnapshot,
    QuotaWindow,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://platform.xiaomimimo.com"

# Official monthly plan limits (Credits) — from the MiMo Token Plan docs.
_PLAN_LIMITS_MONTHLY: dict[str, int] = {
    "lite": 4_100_000_000,       # 4.1 B
    "standard": 11_000_000_000,  # 11 B
    "pro": 38_000_000_000,       # 38 B
    "max": 82_000_000_000,       # 82 B
}

# Per-token Credit deduction rates for local estimation.
#  key: (model, token_type) -> credits_per_token
_TOKEN_RATES: dict[tuple[str, str], float] = {
    ("mimo-v2.5-pro", "input_cache"): 2.5,
    ("mimo-v2.5-pro", "input_miss"): 300.0,
    ("mimo-v2.5-pro", "output"): 600.0,
    ("mimo-v2.5", "input_cache"): 2.0,
    ("mimo-v2.5", "input_miss"): 100.0,
    ("mimo-v2.5", "output"): 200.0,
}


class XiaomiQuotaProvider(QuotaProvider):
    provider_id = "xiaomi"
    display_name = "小米 MiMo Token Plan"

    @property
    def plan_type(self) -> str:
        return self.config.get("plan_type", "pro")

    @property
    def multipliers(self) -> list[ModelMultiplier]:
        return [
            ModelMultiplier(
                model="mimo-v2.5-pro",
                peak=1.0,
                off_peak=0.8,
                peak_hours="08-24",  # off-peak is 00:00-08:00 Beijing (UTC+8)
            ),
            ModelMultiplier(
                model="mimo-v2.5",
                peak=1.0,
                off_peak=0.8,
                peak_hours="08-24",
            ),
        ]

    async def fetch_quota(self) -> QuotaSnapshot:
        cookie = self.credential
        if cookie:
            try:
                return await self._fetch_api(cookie)
            except Exception as exc:
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
        now_iso = datetime.now(timezone.utc).isoformat()

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
            if raw_type in _PLAN_LIMITS_MONTHLY:
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
        total_credits: float = float(_PLAN_LIMITS_MONTHLY.get(plan_type, 0))

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
            model_multipliers=self.multipliers,
            expires_at=expires_at,
            auto_renew=auto_renew,
            fetched_at=now_iso,
            source="api",
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
        now_iso = datetime.now(timezone.utc).isoformat()
        total_credits = float(_PLAN_LIMITS_MONTHLY.get(self.plan_type, _PLAN_LIMITS_MONTHLY["pro"]))

        try:
            db = await db_module.get_db()
            # Current billing period: last 30 days (simplified).
            period_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            rows = await db.execute_fetchall(
                """SELECT model,
                          SUM(input_tokens) as input_tokens,
                          SUM(output_tokens) as output_tokens,
                          SUM(cache_read_tokens) as cache_read_tokens,
                          SUM(cache_write_tokens) as cache_write_tokens
                   FROM token_usage
                   WHERE model LIKE 'mimo-%'
                     AND timestamp >= ?
                   GROUP BY model""",
                [period_start],
            )

            used_credits = 0.0
            for row in rows:
                model = (row["model"] or "").lower()
                inp = row["input_tokens"] or 0
                out = row["output_tokens"] or 0
                cache_read = row["cache_read_tokens"] or 0
                cache_write = row["cache_write_tokens"] or 0

                # Approximate: cache_read → cache-hit rate, rest → cache-miss
                cache_miss_input = max(0, inp - cache_read)
                rate_cache = _TOKEN_RATES.get((model, "input_cache"), 0)
                rate_miss = _TOKEN_RATES.get((model, "input_miss"), 0)
                rate_out = _TOKEN_RATES.get((model, "output"), 0)

                used_credits += (
                    cache_read * rate_cache
                    + cache_miss_input * rate_miss
                    + cache_write * rate_miss  # cache writes count as input
                    + out * rate_out
                )
        except Exception as exc:
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
            model_multipliers=self.multipliers,
            fetched_at=now_iso,
            source="estimate",
        )
