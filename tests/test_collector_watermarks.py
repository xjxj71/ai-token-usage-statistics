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


# ── Codex rollout files ────────────────────────────────────────────

def _codex_record_line(ts: str, i: int) -> str:
    return json.dumps(
        {
            "timestamp": ts,
            "type": "token_usage_record",
            "payload": {
                "session_id": "s-codex",
                "turn_id": f"turn-{i}",
                "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10},
            },
        }
    )


def test_codex_positions_persist_and_incremental(tmp_path: Path):
    from backend.collectors.codex import scan_codex_directory

    f = tmp_path / "2026" / "rollout.jsonl"
    f.parent.mkdir()
    f.write_text(
        "\n".join(_codex_record_line(f"2026-01-01T00:00:0{i}.000Z", i) for i in range(3)) + "\n",
        encoding="utf-8",
    )

    records, positions, context = scan_codex_directory(tmp_path, "codex", {}, {})
    assert len(records) == 3
    assert positions == {str(f.relative_to(tmp_path)): f.stat().st_size}

    # Second poll with saved watermarks must not re-collect anything.
    records2, positions2, _ = scan_codex_directory(tmp_path, "codex", positions, context)
    assert records2 == []
    assert positions2 == positions

    # An appended line is picked up incrementally, old lines stay consumed.
    with f.open("a", encoding="utf-8") as fh:
        fh.write(_codex_record_line("2026-01-01T00:00:09.000Z", 9) + "\n")
    records3, _, _ = scan_codex_directory(tmp_path, "codex", positions, context)
    assert len(records3) == 1


def test_codex_unmatched_file_gets_watermark(tmp_path: Path):
    # A rollout file with no usage events must still be marked consumed, or
    # it is re-parsed (including its huge session_meta line) on every poll.
    from backend.collectors.codex import scan_codex_directory

    f = tmp_path / "rollout.jsonl"
    f.write_text(
        '{"type":"session_meta","payload":{"cwd":"/tmp"}}\n{"type":"noise"}\n',
        encoding="utf-8",
    )

    _, positions, _ = scan_codex_directory(tmp_path, "codex", {}, {})
    assert positions == {str(f.relative_to(tmp_path)): f.stat().st_size}


def test_codex_partial_line_not_consumed(tmp_path: Path):
    from backend.collectors.codex import scan_codex_directory

    f = tmp_path / "rollout.jsonl"
    complete = _codex_record_line("2026-01-01T00:00:01.000Z", 1) + "\n"
    full_second = _codex_record_line("2026-01-01T00:00:02.000Z", 2) + "\n"
    partial = full_second[:40]
    f.write_text(complete + partial, encoding="utf-8", newline="")
    size_after_complete = len(complete.encode("utf-8"))

    records, positions, _ = scan_codex_directory(tmp_path, "codex", {}, {})
    assert len(records) == 1
    assert positions == {str(f.relative_to(tmp_path)): size_after_complete}

    f.write_text(complete + full_second, encoding="utf-8", newline="")
    records2, _, _ = scan_codex_directory(tmp_path, "codex", positions, {})
    assert len(records2) == 1


# ── Qoder run logs / transcripts ──────────────────────────────────

def _qoder_dump_line(i: int) -> str:
    """One [permission-check] context line with a single usage-carrying event."""
    event = {
        "type": "assistant",
        "uuid": f"550895cb-fdcb-496d-adbd-1046c514{i:04d}",
        "timestamp": f"2026-11-23T05:48:1{i}.642Z",
        "message": {
            "id": f"chatcmpl-{i}",
            "type": "message",
            "role": "assistant",
            "model": "auto",
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "container": None,
            "context_management": None,
            "usage": {
                "input_tokens": 8474,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 7424,
                "output_tokens": 855,
            },
            "content": [{"type": "text", "text": "ok"}],
        },
        "requestId": f"req-{i}",
        "responseGroupId": "grp-1",
        "requestTokenAnchor": {"request": "aa", "response": "bb", "requestId": f"req-{i}"},
        "sessionId": "105b1459-2c08-4f7a-b9a2-367b55350152",
        "session_id": "105b1459-2c08-4f7a-b9a2-367b55350152",
    }
    body = '{"messages":[' + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "]}"
    return (
        "2026-11-23T13:48:10.692+08:00 INFO  debug.message [permission-check] "
        f"context tool=Bash callId={i} agentId=a1 context={body}"
    )


def _qoder_compact_line(i: int) -> str:
    return json.dumps({
        "type": "system",
        "uuid": f"713ad13a-a7c1-48c9-9627-2cda6d39cc{i:02d}",
        "timestamp": f"2026-11-23T06:03:2{i}.830Z",
        "subtype": "compact_boundary",
        "compactUsage": {
            "input_tokens": 164173,
            "output_tokens": 6240,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 162816,
        },
        "cwd": r"C:\Users\me\demo",
        "sessionId": "105b1459-2c08-4f7a-b9a2-367b55350152",
    }, ensure_ascii=False)


def test_qoder_log_positions_persist_and_incremental(tmp_path: Path):
    from backend.collectors.qoder import scan_qoder_logs

    f = tmp_path / "run-1" / "qodercli.log"
    f.parent.mkdir()
    f.write_text(_qoder_dump_line(1) + "\n", encoding="utf-8")

    records, positions = scan_qoder_logs(tmp_path, "qoder", {}, {})
    assert len(records) == 1
    assert positions == {str(f.relative_to(tmp_path)): f.stat().st_size}

    # No growth: nothing new, positions carried forward unchanged.
    records2, positions2 = scan_qoder_logs(tmp_path, "qoder", positions, {})
    assert records2 == []
    assert positions2 == positions

    with open(f, "a", encoding="utf-8") as fh:
        fh.write(_qoder_dump_line(2) + "\n")
    records3, positions3 = scan_qoder_logs(tmp_path, "qoder", positions, {})
    assert len(records3) == 1
    assert records3[0].timestamp.endswith("2.642Z")
    assert positions3[str(f.relative_to(tmp_path))] == f.stat().st_size


def test_qoder_log_partial_line_not_consumed(tmp_path: Path):
    from backend.collectors.qoder import scan_qoder_logs

    f = tmp_path / "qodercli.log"
    complete = _qoder_dump_line(1) + "\n"
    full_second = _qoder_dump_line(2) + "\n"
    partial = full_second[:40]
    f.write_text(complete + partial, encoding="utf-8", newline="")
    size_after_complete = len(complete.encode("utf-8"))

    records, positions = scan_qoder_logs(tmp_path, "qoder", {}, {})
    assert len(records) == 1
    assert positions == {str(f.relative_to(tmp_path)): size_after_complete}

    f.write_text(complete + full_second, encoding="utf-8", newline="")
    records2, _ = scan_qoder_logs(tmp_path, "qoder", positions, {})
    assert len(records2) == 1


def test_qoder_transcript_truncation_resets(tmp_path: Path):
    from backend.collectors.qoder import scan_qoder_transcripts

    f = tmp_path / "session.jsonl"
    f.write_text(
        json.dumps({"type": "runtime-config", "sessionId": "s1", "model": "kmodel-latest"}) + "\n"
        + _qoder_compact_line(1) + "\n",
        encoding="utf-8",
    )

    records, positions, context, session_cwd = scan_qoder_transcripts(tmp_path, "qoder", {}, {})
    assert len(records) == 1
    key = str(f.relative_to(tmp_path))
    assert positions[key] == f.stat().st_size
    assert context[key]["model"] == "kmodel-latest"
    assert session_cwd["105b1459-2c08-4f7a-b9a2-367b55350152"] == r"C:\Users\me\demo"

    # Truncate to a strictly shorter replacement: stale watermark and the
    # learned model context must both reset.
    f.write_text(_qoder_compact_line(2) + "\n", encoding="utf-8")
    records2, positions2, context2, _ = scan_qoder_transcripts(
        tmp_path, "qoder", positions, context
    )
    assert len(records2) == 1
    assert records2[0].model == "unknown"
    assert positions2[key] == f.stat().st_size
    assert context2.get(key, {}).get("model") is None
