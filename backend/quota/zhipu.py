"""Zhipu GLM Coding Plan quota provider.

The Zhipu open platform (bigmodel.cn) does **not** expose a public API-key
endpoint for querying subscription balance.  Instead, the web console calls
internal endpoints under ``/api/biz/user/`` authenticated by a browser
session token (extracted from cookies).

When a valid ``session_token`` is supplied in the provider config, we call:

    GET /api/biz/user/subscription/list      — plan info (Lite/Pro/Max)
    GET /api/biz/user/subscription/usage     — 5h + weekly usage
    GET /api/biz/user/account/balance        — cash + gift balance

When no token is available or the API returns 401, we fall back to a local
estimate computed from the ``token_usage`` table.
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

_BASE_URL = "https://open.bigmodel.cn"

# Official plan limits (prompts) — from the GLM Coding Plan documentation.
_PLAN_LIMITS: dict[str, dict[str, int]] = {
    "lite": {"window_5h": 80, "weekly": 400},
    "pro": {"window_5h": 400, "weekly": 2000},
    "max": {"window_5h": 1600, "weekly": 8000},
}

# Default model consumption multipliers.
_DEFAULT_MULTIPLIERS = [
    ModelMultiplier(model="glm-5.2", peak=3.0, off_peak=2.0, peak_hours="14-18"),
    ModelMultiplier(model="glm-5-turbo", peak=3.0, off_peak=2.0, peak_hours="14-18"),
    ModelMultiplier(model="glm-4.7", peak=1.0, off_peak=1.0),
]


class ZhipuQuotaProvider(QuotaProvider):
    provider_id = "zhipu"
    display_name = "智谱 GLM Coding Plan"

    @property
    def plan_type(self) -> str:
        return self.config.get("plan_type", "pro")

    @property
    def multipliers(self) -> list[ModelMultiplier]:
        return list(_DEFAULT_MULTIPLIERS)

    async def fetch_quota(self) -> QuotaSnapshot:
        token = self.credential
        if not token:
            return await self._estimate()

        # API keys (format: "xxx.yyy") cannot access the web-only
        # subscription API.  Only session tokens from browser cookies
        # work.  Detect the format and skip the external call for API
        # keys to avoid unnecessary timeouts.
        if self._is_api_key(token):
            return await self._estimate()

        try:
            return await self._fetch_api(token)
        except Exception as exc:
            logger.warning("Zhipu API fetch failed, falling back to estimate: %s", exc)
            snapshot = await self._estimate()
            snapshot.error = str(exc)
            return snapshot

    @staticmethod
    def _is_api_key(credential: str) -> bool:
        """Heuristic: API keys are typically ``hex.hex`` (~40 chars).
        Session tokens are much longer (100+ chars) or contain ``=``.
        """
        cred = credential.strip()
        if len(cred) > 80:
            return False  # long string → likely session token
        if "=" in cred or ";" in cred:
            return False  # cookie-like → session token
        parts = cred.split(".")
        return len(parts) == 2 and len(parts[0]) > 10  # xxx.yyy format

    # ── API path ───────────────────────────────────────────────

    async def _fetch_api(self, token: str) -> QuotaSnapshot:
        """Query Zhipu internal web API using a browser session token.

        The bigmodel.cn frontend SPA sends an ``Authorization: Bearer``
        header populated from localStorage.  We replicate that here.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "ai-token-usage/1.0",
        }

        sub_list = await self._http_get(
            f"{_BASE_URL}/api/biz/user/subscription/list", headers
        )
        usage = await self._http_get(
            f"{_BASE_URL}/api/biz/user/subscription/usage", headers
        )
        balance = await self._http_get(
            f"{_BASE_URL}/api/biz/user/account/balance", headers
        )

        return self._parse_api_response(sub_list, usage, balance)

    def _parse_api_response(
        self,
        sub_data: dict,
        usage_data: dict,
        balance_data: dict,
    ) -> QuotaSnapshot:
        now_iso = datetime.now(timezone.utc).isoformat()

        # --- Plan info ---
        plan_name = "Unknown"
        plan_type = self.plan_type
        expires_at: str | None = None
        auto_renew: bool | None = None

        sub_items = sub_data.get("data") or sub_data.get("list") or []
        if isinstance(sub_items, list) and sub_items:
            sub = sub_items[0]
            plan_name = sub.get("planName") or sub.get("plan_name") or sub.get("name", "Unknown")
            raw_type = (sub.get("planType") or sub.get("plan_type") or "").lower()
            if raw_type in _PLAN_LIMITS:
                plan_type = raw_type
            expires_at = sub.get("expireTime") or sub.get("expire_time") or sub.get("expiresAt")
            auto_renew = sub.get("autoRenew") or sub.get("auto_renew")

        # --- Usage ---
        windows: list[QuotaWindow] = []
        u_data = usage_data.get("data") or usage_data or {}

        w5h_used = u_data.get("fiveHourUsed") or u_data.get("window_5h_used")
        w5h_total = u_data.get("fiveHourTotal") or u_data.get("window_5h_total")
        w5h_reset = u_data.get("fiveHourResetAt") or u_data.get("window_5h_reset_at")
        if w5h_total is not None:
            windows.append(QuotaWindow(
                used=float(w5h_used or 0),
                total=float(w5h_total),
                unit="prompts",
                reset_at=w5h_reset,
            ))

        wk_used = u_data.get("weeklyUsed") or u_data.get("weekly_used")
        wk_total = u_data.get("weeklyTotal") or u_data.get("weekly_total")
        wk_reset = u_data.get("weeklyResetAt") or u_data.get("weekly_reset_at")
        if wk_total is not None:
            windows.append(QuotaWindow(
                used=float(wk_used or 0),
                total=float(wk_total),
                unit="prompts",
                reset_at=wk_reset,
            ))

        # --- Balance ---
        b_data = balance_data.get("data") or balance_data or {}
        cash_balance = b_data.get("cashBalance") or b_data.get("balance")
        gift_balance = b_data.get("giftBalance") or b_data.get("free_balance")

        main = windows[0] if windows else None
        extra = windows[1:] if len(windows) > 1 else []

        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=plan_name,
            plan_type=plan_type,
            main_window=main,
            extra_windows=extra,
            balance=float(cash_balance) if cash_balance is not None else None,
            free_balance=float(gift_balance) if gift_balance is not None else None,
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
        """Estimate consumption from the local ``token_usage`` table.

        The Coding Plan measures in "prompts" (1 prompt ≈ 15-20 model
        calls).  We estimate prompts by counting GLM model calls and
        dividing by 15.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        limits = _PLAN_LIMITS.get(self.plan_type, _PLAN_LIMITS["pro"])
        avg_calls_per_prompt = 15  # official estimate

        try:
            db = await db_module.get_db()
            # 5h window: count GLM model calls.
            five_h_ago = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            rows = await db.execute_fetchall(
                """SELECT COUNT(*) as cnt
                   FROM token_usage
                   WHERE model LIKE 'glm-%'
                     AND timestamp >= ?
                     AND agent != 'openrouter'""",
                [five_h_ago],
            )
            calls_5h = float(rows[0]["cnt"]) if rows else 0.0
            estimated_5h = calls_5h / avg_calls_per_prompt

            # Weekly window: 7 days.
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            rows = await db.execute_fetchall(
                """SELECT COUNT(*) as cnt
                   FROM token_usage
                   WHERE model LIKE 'glm-%'
                     AND timestamp >= ?
                     AND agent != 'openrouter'""",
                [week_ago],
            )
            calls_weekly = float(rows[0]["cnt"]) if rows else 0.0
            estimated_weekly = calls_weekly / avg_calls_per_prompt
        except Exception as exc:
            logger.warning("Zhipu local estimate failed: %s", exc)
            estimated_5h = 0.0
            estimated_weekly = 0.0

        main_window = QuotaWindow(
            used=estimated_5h,
            total=float(limits["window_5h"]),
            unit="prompts",
        )
        weekly_window = QuotaWindow(
            used=estimated_weekly,
            total=float(limits["weekly"]),
            unit="prompts",
        )

        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=self.plan_type.capitalize(),
            plan_type=self.plan_type,
            main_window=main_window,
            extra_windows=[weekly_window],
            model_multipliers=self.multipliers,
            fetched_at=now_iso,
            source="estimate",
        )
