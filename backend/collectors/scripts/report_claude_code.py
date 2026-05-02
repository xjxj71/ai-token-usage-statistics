#!/usr/bin/env python3
"""Claude Code PostToolUse hook script.

Receives tool usage data and writes it as a JSON file
for the token-statistic collector to pick up.

Install: place this script at ~/.claude/token-statistic/report_token.py
"""
import json
import os
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

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": data.get("model", "unknown"),
        "session_id": data.get("session_id", ""),
        "usage": usage,
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    filename = f"usage-{ts}.json"
    (OUTPUT_DIR / filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
