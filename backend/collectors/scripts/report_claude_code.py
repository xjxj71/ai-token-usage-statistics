#!/usr/bin/env python3
"""Claude Code PostToolUse 钩子脚本。

接收工具使用数据，将其写入 JSON 文件，
供 Token 统计采集器读取。

安装：将此脚本放置于 ~/.claude/token-statistic/report_token.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_DIR = Path.home() / ".claude" / "token-statistic"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Read hook input from stdin or argument
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    if not raw:
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    # Extract usage info
    usage = data.get("usage", {})
    if not usage:
        usage = {
            "input_tokens": data.get("input_tokens", 0),
            "output_tokens": data.get("output_tokens", 0),
            "cache_read_input_tokens": data.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": data.get("cache_creation_input_tokens", 0),
        }

    now = datetime.now(timezone.utc)

    record = {
        "timestamp": now.isoformat(),
        "model": data.get("model", "unknown"),
        "session_id": data.get("session_id", ""),
        "usage": usage,
    }

    ts = now.strftime("%Y%m%dT%H%M%S%f")
    filename = f"usage-{ts}.json"
    (OUTPUT_DIR / filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
