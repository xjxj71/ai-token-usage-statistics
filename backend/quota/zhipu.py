"""Zhipu GLM Coding Plan quota provider.

Two credential types are supported, both **user-supplied** via the
frontend settings panel (stored in ``config/quota_providers.yaml``):

1. **API key** (format ``xxx.yyy``) — queries the Coding Plan usage
   endpoint (same one cc-switch uses; bigmodel.cn and z.ai share the
   backend and JSON shape)::

       GET /api/monitor/usage/quota/limit
       Authorization: <api_key>        (no Bearer prefix — Zhipu quirk)

   Returns per-window **used percentage** (not absolute values) plus the
   plan ``level``.  Absolute used/total are back-computed from the
   official plan limits so the usage *ratio* is exact regardless of the
   limits table's accuracy.  This endpoint does not expose account
   balance or expiry.

2. **Browser session token** — queries the web-console endpoints, which
   carry absolute usage numbers *and* cash balance / expiry::

       GET /api/biz/user/subscription/list      — plan info (Lite/Pro/Max)
       GET /api/biz/user/subscription/usage     — 5h + weekly usage
       GET /api/biz/user/account/balance        — cash + gift balance

When no credential is supplied or the external call fails, we fall back
to a local estimate computed from the ``token_usage`` table.  Credentials
are never auto-discovered from other tools' config files — only the
user-entered value from this app's own settings is used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from backend.db import database as db_module
from backend.quota import multipliers as mult_module
from backend.quota.base import (
    ModelMultiplier,
    QuotaProvider,
    QuotaSnapshot,
    QuotaWindow,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://open.bigmodel.cn"


class ZhipuQuotaProvider(QuotaProvider):
    provider_id = "zhipu"
    display_name = "智谱 GLM Coding Plan"

    def __init__(self, config: dict):
        super().__init__(config)
        # "credits" = 当前积分制套餐; "prompts" = 历史 V2 prompt 制套餐.
        # auto: 从用量接口的 limits[].type 推断，未识别前默认按积分制展示。
        self._detected_mode: str = ""

    @property
    def plan_type(self) -> str:
        return self.config.get("plan_type", "pro")

    @property
    def mode(self) -> str:
        configured = str(self.config.get("plan_mode", "auto")).strip().lower()
        if configured in ("credits", "prompts"):
            return configured
        return self._detected_mode or "credits"

    @property
    def multipliers(self) -> list[ModelMultiplier]:
        return list(mult_module.get_set(self.provider_id, self.mode).models)

    async def fetch_quota(self) -> QuotaSnapshot:
        token = self.credential
        if not token:
            return await self._estimate()

        # API keys (format "xxx.yyy") use the Coding Plan usage endpoint
        # (method adopted from cc-switch).  Session tokens from browser
        # cookies use the web-console endpoints below.
        if self._is_api_key(token):
            return await self._fetch_via_api_key(token)

        try:
            return await self._fetch_api(token)
        except Exception as exc:  # noqa: BLE001
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

    # ── API-key path (Coding Plan usage endpoint) ──────────────

    async def _fetch_via_api_key(self, api_key: str) -> QuotaSnapshot:
        """Query the Coding Plan usage endpoint with a plain API key.

        Returns a live snapshot on success; falls back to the local
        estimate (with ``error`` set) on any failure — never raises.
        """
        try:
            headers = {
                # Zhipu's coding-plan endpoint takes the raw key — no
                # Bearer prefix (verified in cc-switch's implementation).
                "Authorization": api_key.strip(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Language": "en-US,en",
                "User-Agent": "ai-token-usage/1.0",
            }
            body = await self._http_get(
                f"{_BASE_URL}/api/monitor/usage/quota/limit", headers
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Zhipu coding-plan query failed, falling back to estimate: %s", exc
            )
            snapshot = await self._estimate()
            snapshot.error = f"API Key 查询失败: {exc}"
            return snapshot

        snapshot = self._parse_coding_plan_response(body)
        if snapshot is None:
            logger.warning(
                "Zhipu coding-plan response unparseable, falling back to estimate"
            )
            snapshot = await self._estimate()
            snapshot.error = "Coding Plan 接口响应无法解析，已回退估算模式"
        return snapshot

    def _parse_coding_plan_response(self, body: dict) -> QuotaSnapshot | None:
        """Parse the ``/api/monitor/usage/quota/limit`` response.

        Window classification follows cc-switch's field-tested logic:

        * ``unit: 3`` → 5-hour rolling window; ``unit: 6`` → weekly.
          Classification must anchor on ``unit`` — sorting by reset time
          mislabels the buckets near the end of a weekly cycle, where the
          weekly window resets *earlier* than the 5-hour one.
        * Fallback when ``unit`` is missing/unrecognized: entries without
          ``nextResetTime`` go to the 5-hour slot first (a 0%-used 5h
          bucket has no reset time), the rest fill empty slots by reset
          time ascending.
        * Legacy plans (pre-2026-02-12) return a single limit — the
          weekly window is then simply absent.

        ``percentage`` is the **used** percentage.  The endpoint has no
        absolute numbers, so used/total are back-computed from the plan
        limits — the resulting *ratio* equals percentage/100 exactly.
        """
        if not isinstance(body, dict):
            return None
        if body.get("success") is False:
            logger.warning("Zhipu coding-plan API error: %s", body.get("msg"))
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None

        plan_type = self.plan_type

        five_hour: tuple[int | None, float] | None = None
        weekly: tuple[int | None, float] | None = None
        unclassified: list[tuple[int | None, float]] = []
        seen_types: set[str] = set()

        for item in data.get("limits") or []:
            if not isinstance(item, dict):
                continue
            limit_type = str(item.get("type") or "").upper()
            if limit_type not in ("TOKENS_LIMIT", "CREDIT_LIMIT"):
                continue
            seen_types.add(limit_type)
            try:
                pct = float(item.get("percentage") or 0.0)
            except (TypeError, ValueError):
                pct = 0.0
            reset_ms = item.get("nextResetTime")
            if not isinstance(reset_ms, (int, float)):
                reset_ms = None
            entry: tuple[int | None, float] = (reset_ms, pct)
            unit = item.get("unit")
            if unit == 3 and five_hour is None:
                five_hour = entry
            elif unit == 6 and weekly is None:
                weekly = entry
            else:
                # Unknown unit, or a duplicate for an already-filled slot.
                unclassified.append(entry)

        # 套餐制式：CREDIT_LIMIT → 新版积分制；TOKENS_LIMIT → 历史 V2 prompt 制。
        if seen_types == {"CREDIT_LIMIT"}:
            self._detected_mode = "credits"
        elif seen_types == {"TOKENS_LIMIT"}:
            self._detected_mode = "prompts"

        mode = self.mode
        plan_limits = mult_module.get_plan_limits(self.provider_id, mode)
        # Plan level — trust the API when it names a known plan,
        # otherwise keep the user-configured plan_type.
        level = str(data.get("level") or "").strip().lower()
        if level in plan_limits:
            plan_type = level
        limits = plan_limits.get(plan_type) or plan_limits.get("pro") or {}
        unit = "credits" if mode == "credits" else "prompts"

        # Fallback heuristic: no-reset entries prefer the 5-hour slot,
        # then ascending reset time fills the remaining empty slot.
        unclassified.sort(key=lambda e: (e[0] is not None, e[0] if e[0] is not None else 0))
        for entry in unclassified:
            if five_hour is None:
                five_hour = entry
            elif weekly is None:
                weekly = entry

        def _window(entry: tuple[int | None, float], total: float) -> QuotaWindow:
            reset_ms, pct = entry
            reset_iso = None
            if reset_ms is not None:
                try:
                    reset_iso = datetime.fromtimestamp(reset_ms / 1000, tz=UTC).isoformat()
                except (OverflowError, OSError, ValueError):
                    reset_iso = None
            return QuotaWindow(
                used=round(total * pct / 100.0, 1),
                total=total,
                unit=unit,
                reset_at=reset_iso,
            )

        main = _window(five_hour, float(limits.get("window_5h", 0.0))) if five_hour else None
        extra = [_window(weekly, float(limits.get("weekly", 0.0)))] if weekly else []

        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=plan_type.capitalize(),
            plan_type=plan_type,
            main_window=main,
            extra_windows=extra,
            fetched_at=datetime.now(UTC).isoformat(),
            source="api",
            **mult_module.snapshot_kwargs(self.provider_id, mode),
        )

    # ── Session-token path (web-console endpoints) ─────────────

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
        now_iso = datetime.now(UTC).isoformat()

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
            if raw_type in mult_module.get_plan_limits(self.provider_id, self.mode):
                plan_type = raw_type
            expires_at = sub.get("expireTime") or sub.get("expire_time") or sub.get("expiresAt")
            auto_renew = sub.get("autoRenew") or sub.get("auto_renew")

        # --- Usage ---
        windows: list[QuotaWindow] = []
        u_data = usage_data.get("data") or usage_data or {}
        unit = "credits" if self.mode == "credits" else "prompts"

        w5h_used = u_data.get("fiveHourUsed") or u_data.get("window_5h_used")
        w5h_total = u_data.get("fiveHourTotal") or u_data.get("window_5h_total")
        w5h_reset = u_data.get("fiveHourResetAt") or u_data.get("window_5h_reset_at")
        if w5h_total is not None:
            windows.append(QuotaWindow(
                used=float(w5h_used or 0),
                total=float(w5h_total),
                unit=unit,
                reset_at=w5h_reset,
            ))

        wk_used = u_data.get("weeklyUsed") or u_data.get("weekly_used")
        wk_total = u_data.get("weeklyTotal") or u_data.get("weekly_total")
        wk_reset = u_data.get("weeklyResetAt") or u_data.get("weekly_reset_at")
        if wk_total is not None:
            windows.append(QuotaWindow(
                used=float(wk_used or 0),
                total=float(wk_total),
                unit=unit,
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
            expires_at=expires_at,
            auto_renew=auto_renew,
            fetched_at=now_iso,
            source="api",
            **mult_module.snapshot_kwargs(self.provider_id, self.mode),
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

    def _coefficients(self, model: str) -> tuple[float, float, float]:
        """(input, cached, output) 抵扣系数 for a token_usage model name.

        Falls back to the first set model (flagship) for unrecognised
        historical names like ``glm-5.1``.
        """
        models = mult_module.get_set(self.provider_id, self.mode).models
        name = (model or "").lower()
        match: ModelMultiplier | None = None
        for m in models:
            if ((name == m.model or name.startswith(m.model))
                    and (match is None or len(m.model) > len(match.model))):
                match = m
        if match is None and models:
            match = models[0]
        if match is None or match.input_rate is None:
            return (0.0, 0.0, 0.0)
        return (match.input_rate, match.cached_rate or 0.0, match.output_rate or 0.0)

    async def _estimate_credits(self) -> tuple[float, float]:
        """Estimate credit consumption from the local ``token_usage`` table.

        模型消耗积分数 =（输入 × Input 抵扣系数 + 缓存命中 × Cached 抵扣系数
        + 输出 × Output 抵扣系数）/ 10000
        """
        totals = {"5h": 0.0, "weekly": 0.0}
        windows = {"5h": timedelta(hours=5), "weekly": timedelta(days=7)}
        now = datetime.now(UTC)
        try:
            db = await db_module.get_db()
            for slot, delta in windows.items():
                rows = await db.execute_fetchall(
                    """SELECT model,
                              SUM(input_tokens) as input_tokens,
                              SUM(output_tokens) as output_tokens,
                              SUM(cache_read_tokens) as cache_read_tokens,
                              SUM(cache_write_tokens) as cache_write_tokens
                       FROM token_usage
                       WHERE model LIKE 'glm-%'
                         AND timestamp >= ?
                         AND agent != 'openrouter'
                       GROUP BY model""",
                    [(now - delta).isoformat()],
                )
                credits = 0.0
                for row in rows:
                    inp = float(row["input_tokens"] or 0)
                    out = float(row["output_tokens"] or 0)
                    cache_read = float(row["cache_read_tokens"] or 0)
                    cache_write = float(row["cache_write_tokens"] or 0)
                    rate_in, rate_cache, rate_out = self._coefficients(row["model"] or "")
                    # token_usage.input_tokens 入库时已是「未命中缓存」口径
                    # （采集器把缓存读/写拆到了独立列），不能再减 cache_read。
                    credits += (
                        (inp + cache_write) * rate_in
                        + cache_read * rate_cache
                        + out * rate_out
                    ) / 10_000.0
                totals[slot] = credits
        except Exception as exc:  # noqa: BLE001
            logger.warning("Zhipu credit estimate failed: %s", exc)
        return totals["5h"], totals["weekly"]

    async def _estimate(self) -> QuotaSnapshot:
        """Estimate consumption from the local ``token_usage`` table.

        积分制套餐按 Token × 抵扣系数 折算积分；历史 V2 prompt 制套餐
        按 GLM 调用次数 ÷ 15 估算 prompts（一次 prompt ≈ 15-30 次调用）。
        """
        now_iso = datetime.now(UTC).isoformat()
        mode = self.mode
        limits = mult_module.get_plan_limits(self.provider_id, mode).get(
            self.plan_type
        ) or {"window_5h": 0.0, "weekly": 0.0}
        unit = "credits" if mode == "credits" else "prompts"

        if mode == "credits":
            estimated_5h, estimated_weekly = await self._estimate_credits()
        else:
            avg_calls_per_prompt = 15  # official estimate
            try:
                db = await db_module.get_db()
                five_h_ago = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
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

                week_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat()
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("Zhipu local estimate failed: %s", exc)
                estimated_5h = 0.0
                estimated_weekly = 0.0

        main_window = QuotaWindow(
            used=estimated_5h,
            total=float(limits.get("window_5h", 0.0)),
            unit=unit,
        )
        weekly_window = QuotaWindow(
            used=estimated_weekly,
            total=float(limits.get("weekly", 0.0)),
            unit=unit,
        )

        return QuotaSnapshot(
            provider=self.provider_id,
            display_name=self.display_name,
            plan_name=self.plan_type.capitalize(),
            plan_type=self.plan_type,
            main_window=main_window,
            extra_windows=[weekly_window],
            fetched_at=now_iso,
            source="estimate",
            **mult_module.snapshot_kwargs(self.provider_id, mode),
        )
