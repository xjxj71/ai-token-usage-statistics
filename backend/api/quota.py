"""Quota monitoring API routes.

Provides endpoints for the frontend to:
  - GET  /api/quota            — fetch all provider snapshots (cached)
  - POST /api/quota/refresh    — force-refresh all providers
  - GET  /api/quota/providers  — list configured providers + status
  - PUT  /api/quota/config     — update a provider's config (e.g. session_token)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.quota.base import ModelMultiplier, QuotaSnapshot, QuotaWindow
from backend.quota.registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quota"])

_CONFIG_YAML = Path(__file__).resolve().parent.parent.parent / "config" / "quota_providers.yaml"


# ── Serialisation helpers ──────────────────────────────────────


def _window_to_dict(w: QuotaWindow | None) -> dict[str, Any] | None:
    if w is None:
        return None
    return {
        "used": w.used,
        "total": w.total,
        "remaining": w.remaining,
        "ratio": round(w.ratio, 4),
        "unit": w.unit,
        "reset_at": w.reset_at,
    }


def _multiplier_to_dict(m: ModelMultiplier) -> dict[str, Any]:
    return {
        "model": m.model,
        "peak": m.peak,
        "off_peak": m.off_peak,
        "peak_hours": m.peak_hours,
    }


def _snapshot_to_dict(s: QuotaSnapshot) -> dict[str, Any]:
    return {
        "provider": s.provider,
        "display_name": s.display_name,
        "plan_name": s.plan_name,
        "plan_type": s.plan_type,
        "main_window": _window_to_dict(s.main_window),
        "extra_windows": [_window_to_dict(w) for w in s.extra_windows],
        "balance": s.balance,
        "free_balance": s.free_balance,
        "model_multipliers": [_multiplier_to_dict(m) for m in s.model_multipliers],
        "expires_at": s.expires_at,
        "auto_renew": s.auto_renew,
        "fetched_at": s.fetched_at,
        "source": s.source,
        "error": s.error,
    }


# ── Routes ─────────────────────────────────────────────────────


@router.get("/quota")
async def get_quota():
    """Return cached quota snapshots for all enabled providers."""
    registry = get_registry()
    snapshots = await registry.fetch_all(force_refresh=False)
    return {
        "items": [_snapshot_to_dict(s) for s in snapshots],
        "total": len(snapshots),
    }


@router.post("/quota/refresh")
async def refresh_quota():
    """Force-refresh quota data from all providers."""
    registry = get_registry()
    snapshots = await registry.fetch_all(force_refresh=True)
    return {
        "items": [_snapshot_to_dict(s) for s in snapshots],
        "total": len(snapshots),
    }


@router.get("/quota/providers")
async def get_providers():
    """List all configured providers with their enabled status."""
    registry = get_registry()
    result = []
    for pid, provider in registry.providers.items():
        result.append({
            "provider_id": pid,
            "display_name": provider.display_name,
            "enabled": provider.enabled,
            "has_credential": bool(provider.credential),
            "plan_type": provider.config.get("plan_type", ""),
        })
    return result


# ── Config update ──────────────────────────────────────────────


class ProviderConfigUpdate(BaseModel):
    provider: str = Field(..., description="Provider ID, e.g. 'zhipu' or 'xiaomi'")
    enabled: bool | None = None
    plan_type: str | None = None
    session_token: str | None = None


@router.put("/quota/config")
async def update_provider_config(body: ProviderConfigUpdate):
    """Update a provider's configuration and persist to YAML.

    Only the fields that are provided (non-None) will be updated.
    """
    pid = body.provider

    # Read current config from YAML (or env-derived values won't be persisted).
    raw: dict[str, Any] = {}
    if _CONFIG_YAML.exists():
        try:
            with open(_CONFIG_YAML, "r", encoding="utf-8") as f:  # noqa: ASYNC230
                raw = yaml.safe_load(f) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read %s: %s", _CONFIG_YAML, exc)

    providers = raw.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        raw["providers"] = providers

    prov_cfg = providers.setdefault(pid, {})
    if not isinstance(prov_cfg, dict):
        prov_cfg = {}
        providers[pid] = prov_cfg

    # Apply updates.
    if body.enabled is not None:
        prov_cfg["enabled"] = body.enabled
    if body.plan_type is not None:
        prov_cfg["plan_type"] = body.plan_type
    if body.session_token is not None:
        # Allow clearing by sending an empty string.
        prov_cfg["session_token"] = body.session_token

    # Persist to YAML.
    _CONFIG_YAML.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_CONFIG_YAML, "w", encoding="utf-8") as f:  # noqa: ASYNC230
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write %s: %s", _CONFIG_YAML, exc)
        raise HTTPException(status_code=500, detail=f"Failed to persist config: {exc}")

    # Reload registry to pick up new config.
    get_registry().reload()

    return {"status": "ok", "provider": pid, "config": prov_cfg}
