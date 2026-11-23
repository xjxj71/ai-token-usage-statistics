"""Quota provider abstraction for subscription balance monitoring.

Each provider (Zhipu GLM Coding Plan, Xiaomi MiMo Token Plan, etc.)
implements :class:`QuotaProvider` to fetch the current subscription
balance from the vendor's internal web API.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Re-exported for convenience — consumers serialise multipliers via to_dict().
__all__ = ["ModelMultiplier", "QuotaProvider", "QuotaSnapshot", "QuotaWindow"]


@dataclass
class QuotaWindow:
    """A usage window — e.g. a 5-hour rolling window or a weekly quota."""

    used: float
    total: float
    unit: str = "prompts"  # "prompts" | "credits" | "tokens"
    reset_at: str | None = None  # ISO-8601 timestamp when the window resets

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.used)

    @property
    def ratio(self) -> float:
        """Usage ratio 0.0–1.0."""
        return self.used / self.total if self.total > 0 else 0.0


@dataclass
class ModelMultiplier:
    """Per-model consumption multiplier / credit rates.

    Two official pricing styles are represented:

    * **Prompt-style** (legacy GLM Coding Plan V2) — per-model ``peak`` /
      ``off_peak`` consumption multipliers plus ``peak_hours``.
    * **Credit-style** (current GLM Coding Plan, MiMo Token Plan) —
      per-token-type rates ``input_rate`` / ``cached_rate`` / ``output_rate``
      with a uniform off-peak discount carried in ``off_peak``.
    """

    model: str
    peak: float = 1.0       # multiplier during peak hours
    off_peak: float = 1.0   # multiplier during off-peak hours
    peak_hours: str = ""    # e.g. "14-18" (UTC+8)
    off_peak_label: str = "夜间"  # UI wording: "夜间" | "非高峰"
    input_rate: float | None = None    # 输入（未命中缓存）抵扣系数
    cached_rate: float | None = None   # 输入（命中缓存）抵扣系数
    output_rate: float | None = None   # 输出抵扣系数
    rate_unit: str = ""    # e.g. "积分/万Token" | "Credits/Token"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "peak": self.peak,
            "off_peak": self.off_peak,
            "peak_hours": self.peak_hours,
            "off_peak_label": self.off_peak_label,
            "input_rate": self.input_rate,
            "cached_rate": self.cached_rate,
            "output_rate": self.output_rate,
            "rate_unit": self.rate_unit,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelMultiplier:
        def _f(key: str) -> float | None:
            v = d.get(key)
            return float(v) if v is not None else None

        return cls(
            model=str(d.get("model", "")),
            peak=float(d.get("peak") or 1.0),
            off_peak=float(d.get("off_peak") or 1.0),
            peak_hours=str(d.get("peak_hours") or ""),
            off_peak_label=str(d.get("off_peak_label") or "夜间"),
            input_rate=_f("input_rate"),
            cached_rate=_f("cached_rate"),
            output_rate=_f("output_rate"),
            rate_unit=str(d.get("rate_unit") or ""),
        )


@dataclass
class QuotaSnapshot:
    """Normalised snapshot returned by every provider."""

    provider: str               # "zhipu" | "xiaomi" | ...
    display_name: str           # "智谱 GLM Coding Plan"
    plan_name: str              # "Pro" | "Max" | "Lite" | ...
    plan_type: str = ""         # internal code: "pro" | "max" | ...

    # Primary quota window (every provider has at least this).
    main_window: QuotaWindow | None = None

    # Secondary windows (e.g. Zhipu has both 5h and weekly).
    extra_windows: list[QuotaWindow] = field(default_factory=list)

    # Account balance in CNY (may be None when not available).
    balance: float | None = None
    free_balance: float | None = None  #赠送金

    # Model-level consumption multipliers.
    model_multipliers: list[ModelMultiplier] = field(default_factory=list)
    multiplier_note: str = ""            # 单位/折扣/高峰时段说明
    multiplier_source: str = "defaults"  # "live" | "cache" | "defaults"
    multiplier_updated_at: str = ""      # ISO-8601 of the last docs fetch

    # Subscription lifecycle.
    expires_at: str | None = None      # ISO-8601 subscription expiry
    auto_renew: bool | None = None

    fetched_at: str = ""               # ISO-8601 of when we fetched this
    source: str = "api"                # "api" | "estimate" | "error"
    error: str | None = None           # populated when source == "error"


class QuotaProvider(ABC):
    """Abstract base class for all quota providers."""

    provider_id: str = ""
    display_name: str = ""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled", False)

    @property
    def credential(self) -> str:
        """Session token / cookie string used for authentication."""
        return self.config.get("session_token", "") or self.config.get("cookie", "")

    @abstractmethod
    async def fetch_quota(self) -> QuotaSnapshot:
        """Fetch the current quota snapshot from the vendor API.

        Implementations should:
        1. Try the real API when a credential is configured.
        2. Fall back to a local estimate when the credential is missing
           or the API call fails.
        3. Never raise — return a QuotaSnapshot with source="error".
        """
        ...
