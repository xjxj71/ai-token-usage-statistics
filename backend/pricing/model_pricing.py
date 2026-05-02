MODEL_PRICING = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0, "cache_read": 1.875, "cache_write": 18.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.375, "cache_write": 3.75},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
    "gpt-4o": {"input": 2.5, "output": 10.0, "cache_read": 1.25, "cache_write": 0.0},
    "gpt-4.1": {"input": 2.0, "output": 8.0, "cache_read": 0.5, "cache_write": 0.0},
    "o3": {"input": 10.0, "output": 40.0, "cache_read": 2.5, "cache_write": 0.0},
    "o4-mini": {"input": 1.1, "output": 4.4, "cache_read": 0.275, "cache_write": 0.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0, "cache_read": 0.0, "cache_write": 0.0},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.6, "cache_read": 0.0, "cache_write": 0.0},
    "deepseek-v3": {"input": 0.27, "output": 1.1, "cache_read": 0.07, "cache_write": 0.0},
    "deepseek-r1": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.0},
}


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0

    cost = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_read_tokens * pricing.get("cache_read", 0)
        + cache_write_tokens * pricing.get("cache_write", 0)
    ) / 1_000_000

    return round(cost, 6)
