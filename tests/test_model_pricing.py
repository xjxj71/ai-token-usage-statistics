import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.pricing.model_pricing import calculate_cost, MODEL_PRICING


def test_calculate_cost_known_model():
    cost = calculate_cost("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=500_000)
    assert cost == pytest.approx(3.0 + 7.5, abs=0.001)


def test_calculate_cost_with_cache():
    cost = calculate_cost(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=500_000,
        cache_write_tokens=200_000,
    )
    expected = (1_000_000 * 3.0 + 500_000 * 0.375 + 200_000 * 3.75) / 1_000_000
    assert cost == pytest.approx(expected, abs=0.001)


def test_calculate_cost_unknown_model():
    cost = calculate_cost("unknown-model", input_tokens=1000, output_tokens=1000)
    assert cost == 0.0


def test_calculate_cost_zero_tokens():
    cost = calculate_cost("gpt-4o", input_tokens=0, output_tokens=0)
    assert cost == 0.0


def test_all_pricing_entries_have_required_fields():
    for model, prices in MODEL_PRICING.items():
        assert "input" in prices, f"{model} missing input price"
        assert "output" in prices, f"{model} missing output price"
        assert prices["input"] > 0, f"{model} input price must be positive"
        assert prices["output"] > 0, f"{model} output price must be positive"
