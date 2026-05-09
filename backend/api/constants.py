"""Shared constants for the API layer."""

# 无意义的模型名称，不出现在筛选下拉菜单和统计图表中
IGNORED_MODELS = {"0", "unknown", ""}

# 支持的 Agent 白名单，筛选下拉菜单只显示这些
SUPPORTED_AGENTS = {"hermes", "claude-code", "openclaw"}
