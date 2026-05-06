from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Resolve config path relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PRICING_YAML = _PROJECT_ROOT / "config" / "model_pricing.yaml"

# Module-level pricing dict (loaded once, can be reloaded)
MODEL_PRICING: dict[str, dict[str, float]] = {}


def _load_yaml(path: Path | None = None) -> dict[str, dict[str, float]]:
    """Load model pricing from YAML file.

    Returns a dict mapping model name -> {input, output, cache_read?, cache_write?}.
    """
    yaml_path = path or _PRICING_YAML
    if not yaml_path.exists():
        logger.error("Pricing YAML not found: %s", yaml_path)
        return {}

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "models" not in data:
        logger.error("Pricing YAML has no 'models' key: %s", yaml_path)
        return {}

    pricing: dict[str, dict[str, float]] = {}
    for model, prices in data["models"].items():
        if not isinstance(prices, dict):
            logger.warning("Skipping invalid pricing entry for model '%s'", model)
            continue
        pricing[model] = {
            "input": float(prices.get("input", 0)),
            "output": float(prices.get("output", 0)),
            "cache_read": float(prices.get("cache_read", 0)),
            "cache_write": float(prices.get("cache_write", 0)),
        }

    logger.info("Loaded pricing for %d models from %s", len(pricing), yaml_path)
    return pricing


def load_pricing() -> dict[str, dict[str, float]]:
    """Load pricing and update the module-level MODEL_PRICING."""
    global MODEL_PRICING
    MODEL_PRICING = _load_yaml()
    return MODEL_PRICING


def reload_pricing() -> dict[str, dict[str, float]]:
    """Reload pricing from YAML (hot-reload support)."""
    logger.info("Reloading model pricing from YAML...")
    return load_pricing()


def get_pricing(model: str) -> dict[str, float] | None:
    """Get pricing for a specific model."""
    if not MODEL_PRICING:
        load_pricing()
    return MODEL_PRICING.get(model)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    if not MODEL_PRICING:
        load_pricing()

    pricing = MODEL_PRICING.get(model)
    if not pricing:
        logger.warning("Unknown model '%s', cannot calculate cost", model)
        return 0.0

    cost = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_read_tokens * pricing.get("cache_read", 0)
        + cache_write_tokens * pricing.get("cache_write", 0)
    ) / 1_000_000

    return round(cost, 6)


# Auto-load on module import
load_pricing()
