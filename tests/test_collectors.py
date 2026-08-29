import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.collectors.claude_code import ClaudeCodeCollector
from backend.collectors.jsonl_utils import build_token_record, parse_jsonl_line, parse_timestamp
from backend.collectors.openclaw import OpenClawCollector
from backend.collectors.zcode import ZcodeCollector


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
            with (
                patch.object(collector, "_load_state", return_value={}),
                patch.object(collector, "_save_state"),
            ):
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
            with (
                patch.object(collector, "_load_state", return_value={"last_timestamp": "2025-05-02T00:00:00Z"}),
                patch.object(collector, "_save_state"),
            ):
                records = await collector.collect()

        assert len(records) == 0


class TestZcodeCollector:
    @pytest.fixture
    def collector(self):
        return ZcodeCollector()

    @staticmethod
    def _make_db(db_path: Path, rows: list[dict], sessions: dict[str, str] | None = None):
        """Create a minimal ZCode usage db with the given model_usage rows."""
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, title TEXT);
            CREATE TABLE model_usage (
                id TEXT PRIMARY KEY, session_id TEXT, turn_id TEXT, query_source TEXT,
                agent TEXT, attempt_index INTEGER, model_id TEXT,
                started_at INTEGER, completed_at INTEGER,
                input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
                cache_creation_input_tokens INTEGER, cache_read_input_tokens INTEGER
            );
            """
        )
        for sid, directory in (sessions or {}).items():
            conn.execute("INSERT INTO session VALUES (?, ?, ?)", (sid, directory, "title"))
        for r in rows:
            conn.execute(
                "INSERT INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"], r.get("session_id"), r.get("turn_id"), r.get("query_source"),
                    r.get("agent"), r.get("attempt_index", 0), r.get("model_id", "GLM-5.3"),
                    r.get("started_at"), r.get("completed_at"),
                    r.get("input_tokens", 0), r.get("output_tokens", 0),
                    r.get("reasoning_tokens", 0),
                    r.get("cache_creation_input_tokens", 0), r.get("cache_read_input_tokens", 0),
                ),
            )
        conn.commit()
        conn.close()

    @pytest.mark.unit
    def test_name(self, collector):
        assert collector.name == "zcode"

    @pytest.mark.asyncio
    async def test_collect_no_db(self, collector, tmp_path):
        with patch("backend.collectors.zcode.settings") as mock_settings:
            mock_settings.zcode_db_path = str(tmp_path / "missing.db")
            records = await collector.collect()
        assert records == []

    @pytest.mark.asyncio
    async def test_collect_maps_fields(self, collector, tmp_path):
        db = tmp_path / "db.sqlite"
        self._make_db(
            db,
            [
                {
                    "id": "u1", "session_id": "sess-1", "turn_id": "turn-1",
                    "query_source": "main_turn", "agent": "zcode",
                    "started_at": 1746178800900, "completed_at": 1746178802000,
                    "input_tokens": 15391, "output_tokens": 926,
                    "cache_read_input_tokens": 11200,
                    "cache_creation_input_tokens": 64,
                },
                # sub-agent request — still attributed to "zcode"
                {
                    "id": "u2", "session_id": "sess-1", "turn_id": "turn-1",
                    "query_source": "subagent", "agent": "zcode-Explore",
                    "started_at": 1746178803123, "completed_at": 1746178804500,
                    "input_tokens": 500, "output_tokens": 100,
                },
                # all-zero row (errored call) — filtered
                {
                    "id": "u3", "session_id": "sess-1",
                    "started_at": 1746178805000, "completed_at": 1746178806000,
                },
            ],
            {"sess-1": "D:\\proj"},
        )

        with patch("backend.collectors.zcode.settings") as mock_settings:
            mock_settings.zcode_db_path = str(db)
            with (
                patch.object(collector, "_load_state", return_value={}),
                patch.object(collector, "_save_state") as save_state,
            ):
                records = await collector.collect()

        assert len(records) == 2
        assert all(r.agent == "zcode" for r in records)
        first = records[0]
        assert first.model == "glm-5.3"
        assert first.session_id == "sess-1"
        assert first.input_tokens == 15391
        assert first.output_tokens == 926
        assert first.cache_read_tokens == 11200
        assert first.cache_write_tokens == 64
        assert first.timestamp == "2025-05-02T09:40:00.900Z"
        raw = json.loads(first.raw_data)
        assert raw["cwd"] == "D:\\proj"
        assert raw["query_source"] == "main_turn"
        # Watermark advances to the max completed_at of kept rows
        assert save_state.call_args[0][0]["last_completed_at_ms"] == 1746178804500

    @pytest.mark.asyncio
    async def test_running_row_deferred_until_completed(self, collector, tmp_path):
        db = tmp_path / "db.sqlite"
        self._make_db(
            db,
            [{"id": "u1", "session_id": "s1", "started_at": 1000, "completed_at": None,
              "input_tokens": 0, "output_tokens": 0}],
        )

        with patch("backend.collectors.zcode.settings") as mock_settings:
            mock_settings.zcode_db_path = str(db)
            with (
                patch.object(collector, "_load_state", return_value={}),
                patch.object(collector, "_save_state"),
            ):
                records = await collector.collect()
        assert records == []

        # Request completes — tokens final now; poll with the saved watermark
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE model_usage SET completed_at = 5000, input_tokens = 100, output_tokens = 50 "
            "WHERE id = 'u1'"
        )
        conn.commit()
        conn.close()

        with patch("backend.collectors.zcode.settings") as mock_settings:
            mock_settings.zcode_db_path = str(db)
            with (
                patch.object(collector, "_load_state", return_value={"last_completed_at_ms": 0}),
                patch.object(collector, "_save_state"),
            ):
                records = await collector.collect()

        assert len(records) == 1
        assert records[0].input_tokens == 100

    @pytest.mark.asyncio
    async def test_watermark_incremental(self, collector, tmp_path):
        db = tmp_path / "db.sqlite"
        self._make_db(
            db,
            [
                {"id": "u1", "session_id": "s1", "started_at": 1000, "completed_at": 2000,
                 "input_tokens": 10, "output_tokens": 5},
                {"id": "u2", "session_id": "s1", "started_at": 3000, "completed_at": 4000,
                 "input_tokens": 20, "output_tokens": 8},
            ],
        )

        with patch("backend.collectors.zcode.settings") as mock_settings:
            mock_settings.zcode_db_path = str(db)
            with (
                patch.object(collector, "_load_state",
                             return_value={"last_completed_at_ms": 2000}),
                patch.object(collector, "_save_state"),
            ):
                records = await collector.collect()

        # Only the row past the watermark is collected
        assert len(records) == 1
        assert records[0].input_tokens == 20

    @pytest.mark.asyncio
    async def test_unchanged_source_skips_via_signature(self, collector, tmp_path):
        db = tmp_path / "db.sqlite"
        self._make_db(
            db,
            [{"id": "u1", "session_id": "s1", "started_at": 1000, "completed_at": 2000,
              "input_tokens": 10, "output_tokens": 5}],
        )

        with patch("backend.collectors.zcode.settings") as mock_settings:
            mock_settings.zcode_db_path = str(db)
            # Compute the real signature, then feed it back as saved state
            from backend.collectors.zcode import _source_signature
            sig = _source_signature(Path(db))
            with (
                patch.object(collector, "_load_state",
                             return_value={"last_completed_at_ms": 2000, "source_sig": sig}),
                patch.object(collector, "_save_state"),
            ):
                records = await collector.collect()

        assert records == []


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
