import json
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from backend.collectors.claude_code import ClaudeCodeCollector
from backend.collectors.openclaw import OpenClawCollector


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

    def test_name(self, collector):
        assert collector.name == "openclaw"

    @pytest.mark.asyncio
    async def test_collect_parses_sessions_json(self, collector, tmp_path):
        agent_dir = tmp_path / "agent1" / "sessions"
        agent_dir.mkdir(parents=True)

        session_data = {
            "sessions": [
                {
                    "id": "sess-1",
                    "model": "gpt-4o",
                    "inputTokens": 1000,
                    "outputTokens": 500,
                    "cacheRead": 200,
                    "cacheWrite": 0,
                    "estimatedCostUsd": 0.005,
                    "updatedAt": "2026-05-02T10:00:00Z",
                }
            ]
        }
        (agent_dir / "sessions.json").write_text(json.dumps(session_data), encoding="utf-8")

        with patch.object(collector, "_resolve_sessions_dir", return_value=tmp_path):
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
        agent_dir = tmp_path / "agent1" / "sessions"
        agent_dir.mkdir(parents=True)

        session_data = {
            "sessions": [
                {
                    "id": "sess-old",
                    "model": "gpt-4o",
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "updatedAt": "2026-05-01T00:00:00Z",
                }
            ]
        }
        (agent_dir / "sessions.json").write_text(json.dumps(session_data), encoding="utf-8")

        with patch.object(collector, "_resolve_sessions_dir", return_value=tmp_path):
            with patch.object(collector, "_load_state", return_value={"last_timestamp": "2026-05-02T00:00:00Z"}):
                with patch.object(collector, "_save_state"):
                    records = await collector.collect()

        assert len(records) == 0
