"""Quota provider registry.

Loads provider configurations from ``config/quota_providers.yaml`` (or
environment variables), instantiates the right :class:`QuotaProvider`
subclass for each entry, and caches fetch results in memory for a short
TTL to avoid hammering upstream APIs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backend.quota.base import QuotaProvider, QuotaSnapshot

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_YAML = _PROJECT_ROOT / "config" / "quota_providers.yaml"

# Cache TTL in seconds.
_CACHE_TTL = 120  # 2 minutes

# ── Provider class registry ────────────────────────────────────

_PROVIDERS: dict[str, type[QuotaProvider]] = {}


def _register(cls: type[QuotaProvider]) -> type[QuotaProvider]:
    """Decorator to auto-register a provider class by its ``provider_id``."""
    _PROVIDERS[cls.provider_id] = cls
    return cls


# Importing these modules triggers the _register calls via metaclass.
# We do it manually here to keep the decorator simple.
def _ensure_providers_registered() -> None:
    if _PROVIDERS:
        return
    # Import side-effect: registers class in _PROVIDERS
    from backend.quota.zhipu import ZhipuQuotaProvider
    from backend.quota.xiaomi import XiaomiQuotaProvider

    _PROVIDERS[ZhipuQuotaProvider.provider_id] = ZhipuQuotaProvider
    _PROVIDERS[XiaomiQuotaProvider.provider_id] = XiaomiQuotaProvider


# ── Config loading ─────────────────────────────────────────────


def _load_config() -> dict[str, dict[str, Any]]:
    """Load provider configurations from YAML.

    Falls back to environment variables:

      TOKEN_STAT_ZHIPU_SESSION_TOKEN  → zhipu.session_token
      TOKEN_STAT_ZHIPU_PLAN_TYPE      → zhipu.plan_type
      TOKEN_STAT_XIAOMI_COOKIE        → xiaomi.cookie (session_token)
      TOKEN_STAT_XIAOMI_PLAN_TYPE     → xiaomi.plan_type
    """
    import os

    config: dict[str, dict[str, Any]] = {}

    if _CONFIG_YAML.exists():
        try:
            with open(_CONFIG_YAML, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            providers = raw.get("providers", raw)
            if isinstance(providers, dict):
                for key, val in providers.items():
                    if isinstance(val, dict):
                        config[key] = val
        except Exception as exc:
            logger.warning("Failed to load %s: %s", _CONFIG_YAML, exc)

    # Environment-variable overrides.
    zhipu_token = os.environ.get("TOKEN_STAT_ZHIPU_SESSION_TOKEN", "")
    if zhipu_token:
        config.setdefault("zhipu", {})["session_token"] = zhipu_token

    zhipu_plan = os.environ.get("TOKEN_STAT_ZHIPU_PLAN_TYPE", "")
    if zhipu_plan:
        config.setdefault("zhipu", {})["plan_type"] = zhipu_plan

    xiaomi_cookie = os.environ.get("TOKEN_STAT_XIAOMI_COOKIE", "")
    if xiaomi_cookie:
        config.setdefault("xiaomi", {})["session_token"] = xiaomi_cookie

    xiaomi_plan = os.environ.get("TOKEN_STAT_XIAOMI_PLAN_TYPE", "")
    if xiaomi_plan:
        config.setdefault("xiaomi", {})["plan_type"] = xiaomi_plan

    # Ensure every provider has an "enabled" key (default False).
    for pid in ("zhipu", "xiaomi"):
        cfg = config.setdefault(pid, {})
        cfg.setdefault("enabled", False)

    return config


# ── Registry singleton ─────────────────────────────────────────


class QuotaRegistry:
    """Holds provider instances and caches fetch results."""

    def __init__(self) -> None:
        self._instances: dict[str, QuotaProvider] = {}
        self._cache: dict[str, tuple[QuotaSnapshot, datetime]] = {}
        self._config: dict[str, dict[str, Any]] = {}

    def reload(self) -> None:
        """Reload config and re-instantiate providers."""
        _ensure_providers_registered()
        self._config = _load_config()
        self._instances = {}
        for pid, cfg in self._config.items():
            cls = _PROVIDERS.get(pid)
            if cls is None:
                logger.debug("No provider class registered for '%s', skipping", pid)
                continue
            self._instances[pid] = cls(cfg)
        # Clear cache on reload.
        self._cache = {}
        logger.info(
            "QuotaRegistry loaded %d providers: %s",
            len(self._instances),
            list(self._instances.keys()),
        )

    @property
    def providers(self) -> dict[str, QuotaProvider]:
        if not self._instances:
            self.reload()
        return self._instances

    async def fetch_all(self, force_refresh: bool = False) -> list[QuotaSnapshot]:
        """Fetch quotas from all enabled providers.

        Returns a list of :class:`QuotaSnapshot` objects.  Uses in-memory
        caching with a TTL of :data:`_CACHE_TTL` seconds.
        """
        if not self._instances:
            self.reload()

        snapshots: list[QuotaSnapshot] = []
        now = datetime.now(timezone.utc)

        for pid, provider in self._instances.items():
            if not provider.enabled:
                continue

            cached = self._cache.get(pid)
            if cached and not force_refresh:
                snap, ts = cached
                age = (now - ts).total_seconds()
                if age < _CACHE_TTL:
                    snapshots.append(snap)
                    continue

            try:
                snap = await provider.fetch_quota()
            except Exception as exc:
                logger.error("Provider %s fetch_quota raised: %s", pid, exc, exc_info=True)
                snap = QuotaSnapshot(
                    provider=pid,
                    display_name=getattr(provider, "display_name", pid),
                    plan_name="Error",
                    fetched_at=now.isoformat(),
                    source="error",
                    error=str(exc),
                )

            self._cache[pid] = (snap, now)
            snapshots.append(snap)

        return snapshots


# Module-level singleton.
_registry: QuotaRegistry | None = None


def get_registry() -> QuotaRegistry:
    global _registry
    if _registry is None:
        _registry = QuotaRegistry()
    return _registry
