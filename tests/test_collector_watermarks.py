"""Regression tests: JSONL watermark positions must persist across polls.

The collectors used to call ``f.tell()`` inside ``for line in f:`` text
iteration (an OSError) or stored text-mode tell() cookies that never compare
against ``st_size`` — positions were never usable, so every 5-second poll
re-read every session file from byte 0 (constant CPU burn; the tray build
made the machine sluggish). These tests pin byte-offset watermarks and
incremental reads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from backend.collectors import hanako
from backend.collectors.jsonl_utils import parse_timestamp, scan_jsonl_directory

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _hanako_line(ts: str, i: int) -> str:
    return json.dumps(
        {
            "type": "message",
            "id": f"m{i}",
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "model": "gpt-4o",
                "usage": {
                    "input": 10,
                    "output": 5,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "cost": {"total": 0.001},
                },
            },
        }
    )


def _claude_line(ts: str, i: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "sessionId": f"s{i}",
            "cwd": "/tmp/proj",
            "message": {
                "model": "gpt-4o",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        }
    )


def test_hanako_positions_persist_and_incremental(tmp_path: Path):
    f = tmp_path / "s1.jsonl"
    f.write_text(
        "\n".join(_hanako_line(f"2026-01-01T00:00:0{i}.000Z", i) for i in range(3)) + "\n",
        encoding="utf-8",
    )

    records, max_ts, positions = hanako._scan_sessions(tmp_path, _EPOCH, {}, "hanako")
    assert len(records) == 3
    assert positions == {"s1.jsonl": f.stat().st_size}

    # Second poll with saved watermarks must not re-collect anything.
    records2, _, positions2 = hanako._scan_sessions(
        tmp_path, parse_timestamp(max_ts), positions, "hanako"
    )
    assert records2 == []
    assert positions2 == positions

    # An appended line is picked up incrementally, old lines stay consumed.
    with f.open("a", encoding="utf-8") as fh:
        fh.write(_hanako_line("2026-01-01T00:00:09.000Z", 9) + "\n")
    records3, _, _ = hanako._scan_sessions(
        tmp_path, parse_timestamp(max_ts), positions, "hanako"
    )
    assert len(records3) == 1


def test_hanako_unmatched_file_gets_watermark(tmp_path: Path):
    # A file with no usage records must still be marked consumed, or it is
    # re-read (and re-parsed) on every poll forever.
    f = tmp_path / "plain.jsonl"
    f.write_text('{"type":"other"}\n{"noise": true}\n', encoding="utf-8")

    _, _, positions = hanako._scan_sessions(tmp_path, _EPOCH, {}, "hanako")
    assert positions == {"plain.jsonl": f.stat().st_size}


def test_hanako_partial_line_not_consumed(tmp_path: Path):
    f = tmp_path / "s1.jsonl"
    complete = _hanako_line("2026-01-01T00:00:01.000Z", 1) + "\n"
    full_second = _hanako_line("2026-01-01T00:00:02.000Z", 2) + "\n"
    # Writer mid-append: a truncated prefix of the second line, no newline.
    partial = full_second[:40]
    # newline="" keeps \n as-is so byte-length assertions hold on Windows.
    f.write_text(complete + partial, encoding="utf-8", newline="")
    size_after_complete = len(complete.encode("utf-8"))

    records, _, positions = hanako._scan_sessions(tmp_path, _EPOCH, {}, "hanako")
    assert len(records) == 1
    assert positions == {"s1.jsonl": size_after_complete}

    # Once the line is complete it is collected on the next poll.
    f.write_text(complete + full_second, encoding="utf-8", newline="")
    records2, _, _ = hanako._scan_sessions(tmp_path, _EPOCH, positions, "hanako")
    assert len(records2) == 1


def test_scan_jsonl_directory_positions_persist_and_incremental(tmp_path: Path):
    f = tmp_path / "proj" / "a.jsonl"
    f.parent.mkdir()
    f.write_text(
        "\n".join(_claude_line(f"2026-01-01T00:00:0{i}Z", i) for i in range(3)) + "\n",
        encoding="utf-8",
    )

    records, positions, max_ts = scan_jsonl_directory(tmp_path, "claude-code", _EPOCH, {})
    assert len(records) == 3
    key = str(f.relative_to(tmp_path))
    # Watermarks are true byte offsets, comparable with st_size.
    assert 0 < positions[key] <= f.stat().st_size
    assert positions[key] == f.stat().st_size

    records2, _, _ = scan_jsonl_directory(
        tmp_path, "claude-code", parse_timestamp(max_ts), positions
    )
    assert records2 == []

    with f.open("a", encoding="utf-8") as fh:
        fh.write(_claude_line("2026-01-01T00:00:09Z", 9) + "\n")
    records3, _, _ = scan_jsonl_directory(
        tmp_path, "claude-code", parse_timestamp(max_ts), positions
    )
    assert len(records3) == 1


def test_scan_jsonl_directory_resets_on_truncation(tmp_path: Path):
    f = tmp_path / "proj" / "a.jsonl"
    f.parent.mkdir()
    f.write_text(
        _claude_line("2026-01-01T00:00:01Z", 1) + "\n"
        + _claude_line("2026-01-01T00:00:02Z", 2) + "\n",
        encoding="utf-8",
    )

    _, positions, _ = scan_jsonl_directory(tmp_path, "claude-code", _EPOCH, {})
    key = str(f.relative_to(tmp_path))
    assert positions[key] == f.stat().st_size

    # Truncate to a strictly shorter replacement: the stale watermark must
    # reset so the replacement content is picked up.
    f.write_text(_claude_line("2026-01-02T00:00:01Z", 3) + "\n", encoding="utf-8")
    records, _, _ = scan_jsonl_directory(tmp_path, "claude-code", _EPOCH, positions)
    assert len(records) == 1
