"""Model pricing used for cost estimation.

Two layers, in increasing precedence:

1. ``config/model_pricing.yaml`` — the bundled defaults (USD per million tokens).
2. The ``model_pricing`` table — seeded from the YAML once, then owned by the
   user: editable in the pricing table and refreshable from OpenRouter.

The second layer is what :func:`calculate_cost` bills with.  It used to be
display-only — costs were always computed from the YAML — so a price edited
in the table (or a model the YAML still listed as ``0``) never reached the
numbers shown next to it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

from backend import paths

# Models already warned about in calculate_cost — avoid log spam when a
# collector processes many records for an unpriced model.
_warned_models: set[str] = set()

# Resolved via backend.paths (bundled seed in frozen builds, repo config in dev).
_PRICING_YAML = paths.model_pricing_yaml_path()

# Effective pricing (YAML overlaid by the database table) and its two layers.
MODEL_PRICING: dict[str, dict[str, float]] = {}
_yaml_pricing: dict[str, dict[str, float]] = {}
_db_overlay: dict[str, dict[str, float]] = {}


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


def load_yaml_pricing() -> dict[str, dict[str, float]]:
    """The bundled YAML defaults on their own (no database rows applied)."""
    return _load_yaml()


def _rebuild() -> dict[str, dict[str, float]]:
    # Updated in place: callers hold a reference to MODEL_PRICING itself.
    MODEL_PRICING.clear()
    MODEL_PRICING.update(_yaml_pricing)
    MODEL_PRICING.update(_db_overlay)
    return MODEL_PRICING


def load_pricing() -> dict[str, dict[str, float]]:
    """Reload the YAML defaults and update the module-level MODEL_PRICING.

    Rows already applied with :func:`overlay_pricing` stay in effect.
    """
    global _yaml_pricing
    _yaml_pricing = _load_yaml()
    return _rebuild()


def reload_pricing() -> dict[str, dict[str, float]]:
    """Reload pricing from YAML (hot-reload support)."""
    logger.info("Reloading model pricing from YAML...")
    return load_pricing()


def overlay_pricing(
    db_rows: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Make the database pricing table the runtime truth.

    ``db_rows`` maps model → ``{input, output, cache_read, cache_write}`` for
    every row of the ``model_pricing`` table.  A model present there always
    wins over the YAML — including a deliberate ``0`` — so the price shown in
    the pricing table is the price new records are billed at.  Models that
    only exist in the YAML keep their YAML price.
    """
    global _db_overlay
    _db_overlay = {model: dict(prices) for model, prices in db_rows.items()}
    return _rebuild()


def clear_pricing_overlay() -> dict[str, dict[str, float]]:
    """Drop the database layer, leaving the YAML defaults (tests, tools)."""
    global _db_overlay
    _db_overlay = {}
    return _rebuild()


def get_pricing(model: str) -> dict[str, float] | None:
    """Get pricing for a specific model."""
    if not MODEL_PRICING:
        load_pricing()

    return MODEL_PRICING.get(model)


def cost_from_prices(
    prices: dict[str, float],
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """USD cost of a request under an explicit per-million-token price."""
    return round(
        (
            input_tokens * prices["input"]
            + output_tokens * prices["output"]
            + cache_read_tokens * prices.get("cache_read", 0)
            + cache_write_tokens * prices.get("cache_write", 0)
        )
        / 1_000_000,
        6,
    )


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
        if model not in _warned_models:
            _warned_models.add(model)
            logger.warning("Unknown model '%s', cannot calculate cost", model)
        return 0.0

    return cost_from_prices(pricing, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)


# Auto-load on module import
load_pricing()
