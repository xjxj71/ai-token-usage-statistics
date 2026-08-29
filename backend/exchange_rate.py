"""USD → CNY exchange rate with live fetching, caching, and persistence.

The effective rate is resolved in this order:
1. A live rate fetched from open.er-api.com (no API key required), cached
   in memory for ``_CACHE_TTL`` seconds and persisted to
   ``data/exchange_rate.json`` so restarts reuse the last known value.
2. The persisted value from a previous successful fetch (offline start).
3. The static ``settings.usd_to_cny_rate`` fallback (env-configurable).

Fetch failures never raise — callers always get a usable rate plus a
``source`` marker telling where it came from.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

_LIVE_URL = "https://open.er-api.com/v6/latest/USD"
_CACHE_TTL_SECONDS = 12 * 60 * 60  # rates change daily; 12h is plenty
_FETCH_TIMEOUT = 15


@dataclass(frozen=True)
class RateInfo:
    rate: float
    source: str  # "live" | "fallback"
    fetched_at: str  # ISO timestamp of the live fetch ("" for fallback)


_state_lock = asyncio.Lock()
_cached: RateInfo | None = None


def _persist_path() -> Path:
    return settings.db_path.parent / "exchange_rate.json"


def _load_persisted() -> RateInfo | None:
    path = _persist_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rate = float(data["rate"])
        if rate > 0:
            return RateInfo(rate=rate, source="live", fetched_at=data.get("fetched_at", ""))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        pass
    return None


def _persist(info: RateInfo) -> None:
    path = _persist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"rate": info.rate, "fetched_at": info.fetched_at}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Failed to persist exchange rate: %s", e)


def _fetch_live_blocking() -> float:
    import urllib.request

    req = urllib.request.Request(_LIVE_URL, headers={"User-Agent": "ai-token-usage/1.0"})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rate = float(data["rates"]["CNY"])
    if rate <= 0:
        raise ValueError(f"non-positive CNY rate: {rate}")
    return rate


def _fallback() -> RateInfo:
    return RateInfo(rate=settings.usd_to_cny_rate, source="fallback", fetched_at="")


async def get_rate(force: bool = False) -> RateInfo:
    """Return the effective USD→CNY rate, fetching live when the cache is stale."""
    global _cached
    async with _state_lock:
        now = datetime.now(UTC)
        if not force and _cached is not None:
            age = (now - datetime.fromisoformat(_cached.fetched_at)).total_seconds()
            if age < _CACHE_TTL_SECONDS:
                return _cached

        try:
            rate = await asyncio.to_thread(_fetch_live_blocking)
            info = RateInfo(rate=rate, source="live", fetched_at=now.isoformat())
            _cached = info
            await asyncio.to_thread(_persist, info)
            logger.info("Exchange rate refreshed: 1 USD = %.4f CNY", rate)
            return info
        except Exception as e:  # noqa: BLE001 — never raise, fall back instead
            logger.warning("Live exchange rate fetch failed (%s); using fallback", e)

        if _cached is not None:
            return _cached
        persisted = await asyncio.to_thread(_load_persisted)
        if persisted is not None:
            _cached = persisted
            return persisted
        return _fallback()


def reset_cache() -> None:
    """Clear the in-memory cache (used by tests)."""
    global _cached
    _cached = None
