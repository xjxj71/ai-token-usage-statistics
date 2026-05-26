import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.collectors.claude_code import ClaudeCodeCollector
from backend.collectors.openclaw import OpenClawCollector
from backend.collectors.jsonl_utils import parse_timestamp, build_token_record, parse_jsonl_line


@pytest.fixture
def tmp_state_dir(tmp_path):
    state_file = tmp_path / "collector_state.json"
    return state_file


def _make_json_file(directory: Path, name: str, data: dict) -> Path:
    p = directory / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class TestClaudeCodeCollector:
    @pytest.fixture
    def collector(self, tmp_path):
        c = ClaudeCodeCollector()
        return c

    @pytest.mark.unit
    def test_name(self, collector):
        assert collector.name == "claude-code"

    @pytest.mark.asyncio
    async def test_collect_no_dir(self, collector):
        with patch.object(collector, "_wsl_path", return_value="/nonexistent"):
            records = await collector.collect()
        assert records == []


class TestOpenClawCollector:
    @pytest.fixture
    def collector(self):
        return OpenClawCollector()

    @pytest.mark.unit
    def test_name(self, collector):
        assert collector.name == "openclaw"

    @pytest.mark.asyncio
    async def test_collect_parses_sessions_json(self, collector, tmp_path):
        """OpenClaw sessions.json is a dict keyed by agent session names."""
        session_file = tmp_path / "sessions.json"

        # Correct format: dict keyed by agent names, NOT a list
        session_data = {
            "agent:main:main": {
                "sessionId": "sess-1",
                "model": "gpt-4o",
                "inputTokens": 1000,
                "outputTokens": 500,
                "cacheRead": 200,
                "cacheWrite": 0,
                "estimatedCostUsd": 0.005,
                "updatedAt": 1746178800000,  # 2025-05-02 epoch ms
            }
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")

        with patch("backend.collectors.openclaw.settings") as mock_settings:
            mock_settings.wsl_copy_to_tmp.return_value = True
            mock_settings.openclaw_sessions_path = str(session_file)
            with patch.object(collector, "_load_state", return_value={}):
                with patch.object(collector, "_save_state"):
                    records = await collector.collect()

        assert len(records) == 1
        assert records[0].agent == "openclaw"
        assert records[0].model == "gpt-4o"
        assert records[0].input_tokens == 1000
        assert records[0].output_tokens == 500

    @pytest.mark.asyncio
    async def test_collect_skips_old_records(self, collector, tmp_path):
        session_file = tmp_path / "sessions.json"

        session_data = {
            "agent:main:old": {
                "sessionId": "sess-old",
                "model": "gpt-4o",
                "inputTokens": 100,
                "outputTokens": 50,
                "updatedAt": 1746048000000,  # 2025-05-01 epoch ms
            }
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")

        with patch("backend.collectors.openclaw.settings") as mock_settings:
            mock_settings.wsl_copy_to_tmp.return_value = True
            mock_settings.openclaw_sessions_path = str(session_file)
            with patch.object(collector, "_load_state", return_value={"last_timestamp": "2025-05-02T00:00:00Z"}):
                with patch.object(collector, "_save_state"):
                    records = await collector.collect()

        assert len(records) == 0


class TestJsonlUtils:
    @pytest.mark.unit
    def test_parse_timestamp_iso(self):
        ts = parse_timestamp("2026-05-02T10:00:00Z")
        assert ts.year == 2026
        assert ts.month == 5

    @pytest.mark.unit
    def test_parse_timestamp_epoch_ms(self):
        ts = parse_timestamp(1746178800000)
        assert ts.year == 2025

    @pytest.mark.unit
    def test_parse_timestamp_invalid(self):
        ts = parse_timestamp("not-a-date")
        assert ts.year == 1970

    @pytest.mark.unit
    def test_parse_jsonl_line_valid(self):
        line = json.dumps({
            "type": "assistant",
            "timestamp": "2026-05-02T10:00:00Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        })
        result = parse_jsonl_line(line)
        assert result is not None
        assert result["type"] == "assistant"

    @pytest.mark.unit
    def test_parse_jsonl_line_non_assistant(self):
        line = json.dumps({"type": "human", "message": "hello"})
        assert parse_jsonl_line(line) is None

    @pytest.mark.unit
    def test_parse_jsonl_line_no_usage(self):
        line = json.dumps({"type": "assistant", "message": {"model": "x"}})
        assert parse_jsonl_line(line) is None

    @pytest.mark.unit
    def test_build_token_record(self):
        data = {
            "timestamp": "2026-05-02T10:00:00Z",
            "sessionId": "s1",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 50,
                },
            },
        }
        record = build_token_record(data, "test-agent", include_metadata=False)
        assert record is not None
        assert record.agent == "test-agent"
        assert record.model == "claude-sonnet-4-6"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500

    @pytest.mark.unit
    def test_build_token_record_all_zero(self):
        data = {
            "timestamp": "2026-05-02T10:00:00Z",
            "message": {
                "model": "x",
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        assert build_token_record(data, "test-agent") is None
