import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.collectors.claude_code import ClaudeCodeCollector
from backend.collectors.codex import CodexCollector
from backend.collectors.jsonl_utils import build_token_record, parse_jsonl_line, parse_timestamp
from backend.collectors.openclaw import OpenClawCollector
from backend.collectors.qoder import QoderCollector
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

    @pytest.mark.asyncio
    async def test_collect_skips_when_wsl_stopped(self, collector):
        """WSL guard: must not touch wsl.exe or UNC paths when distro is stopped."""
        with patch("backend.collectors.claude_code.settings") as mock_settings:
            mock_settings.is_wsl_running.return_value = False
            records = await collector.collect()
        assert records == []
        mock_settings.ensure_claude_projects_readable.assert_not_called()


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
            mock_settings.is_wsl_running.return_value = True
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
            mock_settings.is_wsl_running.return_value = True
            mock_settings.wsl_copy_to_tmp.return_value = True
            mock_settings.openclaw_sessions_path = str(session_file)
            with (
                patch.object(collector, "_load_state", return_value={"last_timestamp": "2025-05-02T00:00:00Z"}),
                patch.object(collector, "_save_state"),
            ):
                records = await collector.collect()

        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_collect_skips_when_wsl_stopped(self, collector):
        """WSL guard: must not call wsl_copy_to_tmp when distro is stopped."""
        with patch("backend.collectors.openclaw.settings") as mock_settings:
            mock_settings.is_wsl_running.return_value = False
            records = await collector.collect()
        assert records == []
        mock_settings.wsl_copy_to_tmp.assert_not_called()


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
        # ZCode's input_tokens is the whole prompt (cache included): the record
        # keeps the cache-miss part only, with cache read/write in their columns.
        assert first.input_tokens == 15391 - 11200 - 64
        assert first.output_tokens == 926
        assert first.cache_read_tokens == 11200
        assert first.cache_write_tokens == 64
        assert first.timestamp == "2025-05-02T09:40:00.900Z"
        raw = json.loads(first.raw_data)
        assert raw["prompt_tokens"] == 15391
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


class TestCodexCollector:
    """Codex rollout JSONL parsing — shapes observed from Codex CLI 0.163.0."""

    SESSION_ID = "01a15f88-800a-7ad1-8d7b-36323f9fb50a"

    @staticmethod
    def _line(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _session_meta(cwd=r"C:\Users\Administrator", model=None, cli="0.163.0"):
        payload = {
            "session_id": TestCodexCollector.SESSION_ID,
            "id": TestCodexCollector.SESSION_ID,
            "cwd": cwd,
            "originator": "codex-tui",
            "cli_version": cli,
            "source": "vscode",
        }
        if model:
            payload["provenance"] = {"type": "model", "model": model}
        return {"timestamp": "2026-10-21T17:35:55.843Z", "type": "session_meta", "payload": payload}

    @staticmethod
    def _turn_context(model="mimo-v2.6-pro", cwd=r"C:\Users\Administrator"):
        return {
            "timestamp": "2026-10-21T17:35:55.917Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1", "cwd": cwd, "model": model},
        }

    @staticmethod
    def _usage_record(ts="2026-10-21T17:35:59.230Z", turn="turn-1", response="resp-1", usage=None):
        return {
            "timestamp": ts,
            "type": "token_usage_record",
            "payload": {
                "thread_id": TestCodexCollector.SESSION_ID,
                "turn_id": turn,
                "session_id": TestCodexCollector.SESSION_ID,
                "response_id": response,
                "usage": usage
                or {
                    "input_tokens": 12451,
                    "cached_input_tokens": 4096,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 37,
                    "reasoning_output_tokens": 12,
                    "total_tokens": 12488,
                },
            },
        }

    @staticmethod
    def _token_count(ts="2026-10-21T17:35:59.233Z", usage=None):
        return {
            "timestamp": ts,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": usage or {"input_tokens": 1},
                    "last_token_usage": usage
                    or {
                        "input_tokens": 12451,
                        "cached_input_tokens": 4096,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 37,
                        "reasoning_output_tokens": 12,
                        "total_tokens": 12488,
                    },
                },
            },
        }

    @pytest.fixture
    def collector(self):
        return CodexCollector()

    @pytest.mark.unit
    def test_name(self, collector):
        assert collector.name == "codex"

    @pytest.mark.asyncio
    async def test_collect_no_dir(self, collector, tmp_path):
        with patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path / "missing"):
            records = await collector.collect()
        assert records == []

    @pytest.mark.asyncio
    async def test_collect_maps_fields(self, collector, tmp_path):
        f = tmp_path / "2026" / "10" / "21" / f"rollout-2026-10-21T17-35-44-{self.SESSION_ID}.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text(
            "\n".join(
                [
                    self._line(self._session_meta()),
                    self._line(self._turn_context()),
                    self._line({"timestamp": "x", "type": "event_msg", "payload": {"type": "noise"}}),
                    self._line(self._usage_record()),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with (
            patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state") as save_state,
        ):
            records = await collector.collect()

        assert len(records) == 1
        r = records[0]
        assert r.agent == "codex"
        # OpenAI semantics: input_tokens includes cached — split into uncached + cache_read
        assert r.input_tokens == 12451 - 4096
        assert r.cache_read_tokens == 4096
        assert r.cache_write_tokens == 0
        assert r.output_tokens == 37
        assert r.reasoning_tokens == 12
        assert r.model == "mimo-v2.6-pro"
        assert r.session_id == self.SESSION_ID
        assert r.project == "Administrator"
        assert r.timestamp == "2026-10-21T17:35:59.230Z"
        raw = json.loads(r.raw_data)
        assert raw["response_id"] == "resp-1"
        assert raw["cli_version"] == "0.163.0"
        # Watermark persisted for the nested file: one entry, consumed to EOF.
        state = save_state.call_args[0][0]
        assert len(state["file_positions"]) == 1
        pos_key, pos_val = next(iter(state["file_positions"].items()))
        assert pos_key.endswith(f.name)
        assert pos_val == f.stat().st_size
        # Per-file context cached for incremental resumes.
        assert state["file_context"][pos_key]["model"] == "mimo-v2.6-pro"

    @pytest.mark.asyncio
    async def test_fallback_token_count(self, collector, tmp_path):
        """Older CLIs emit no token_usage_record — parse event_msg/token_count instead."""
        f = tmp_path / "rollout-old.jsonl"
        f.write_text(
            "\n".join(
                [
                    self._line(self._session_meta(cli="0.20.0")),
                    self._line(self._turn_context(model="gpt-5.1-codex-max")),
                    self._line(self._token_count()),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with (
            patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state"),
        ):
            records = await collector.collect()

        assert len(records) == 1
        r = records[0]
        assert r.model == "gpt-5.1-codex-max"
        assert r.input_tokens == 12451 - 4096
        assert r.cache_read_tokens == 4096
        assert r.session_id == self.SESSION_ID

    @pytest.mark.asyncio
    async def test_records_win_over_token_count(self, collector, tmp_path):
        """New CLIs write both events per response — count each response exactly once."""
        f = tmp_path / "rollout.jsonl"
        f.write_text(
            "\n".join(
                [
                    self._line(self._session_meta()),
                    self._line(self._turn_context()),
                    self._line(self._usage_record()),
                    self._line(self._token_count()),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with (
            patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state"),
        ):
            records = await collector.collect()

        assert len(records) == 1
        assert records[0].timestamp == "2026-10-21T17:35:59.230Z"

    @pytest.mark.asyncio
    async def test_all_zero_usage_skipped(self, collector, tmp_path):
        f = tmp_path / "rollout.jsonl"
        zero = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        f.write_text(
            "\n".join(
                [
                    self._line(self._session_meta()),
                    self._line(self._turn_context()),
                    self._line(self._usage_record(usage=zero)),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with (
            patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state"),
        ):
            records = await collector.collect()

        assert records == []

    @pytest.mark.asyncio
    async def test_incremental_resume_uses_cached_context(self, collector, tmp_path):
        """An appended record with no new session_meta/turn_context is still
        attributed via the per-file context cached in collector state."""
        f = tmp_path / "rollout.jsonl"
        f.write_text(
            "\n".join(
                [
                    self._line(self._session_meta()),
                    self._line(self._turn_context()),
                    self._line(self._usage_record()),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        saved: dict = {}
        with (
            patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state", side_effect=lambda s: saved.update(s)),
        ):
            records1 = await collector.collect()
        assert len(records1) == 1

        # Append a bare record — only the file-context cache knows model/session/cwd.
        with f.open("a", encoding="utf-8") as fh:
            fh.write(self._line(self._usage_record(ts="2026-10-21T17:40:00.000Z", turn="turn-2", response="resp-2")) + "\n")

        with (
            patch("backend.collectors.codex._CODEX_SESSIONS_DIR", tmp_path),
            patch.object(collector, "_load_state", return_value=saved),
            patch.object(collector, "_save_state", side_effect=lambda s: saved.update(s)),
        ):
            records2 = await collector.collect()

        assert len(records2) == 1
        r = records2[0]
        assert r.model == "mimo-v2.6-pro"
        assert r.session_id == self.SESSION_ID
        assert r.project == "Administrator"


class TestHermesCollector:
    @pytest.mark.asyncio
    async def test_collect_skips_when_wsl_stopped(self):
        """WSL guard: must not stat UNC paths or call wsl_copy_to_tmp."""
        from backend.collectors.hermes import HermesCollector

        collector = HermesCollector()
        with patch("backend.collectors.hermes.settings") as mock_settings:
            mock_settings.is_wsl_running.return_value = False
            records = await collector.collect()
        assert records == []
        mock_settings.wsl_copy_to_tmp.assert_not_called()

    @pytest.mark.asyncio
    async def test_hermes_win_not_gated_by_wsl_check(self):
        """hermes-win fully overrides collect() — reads LOCALAPPDATA, no WSL guard."""
        from backend.collectors.hermes_win import HermesWindowsCollector

        collector = HermesWindowsCollector()
        assert collector.name == "hermes-win"
        # Missing local db → collect returns [] without any WSL interaction
        with patch("backend.collectors.hermes_win.settings") as mock_settings:
            mock_settings.hermes_win_db_path = "D:/nonexistent/hermes/state.db"
            records = await collector.collect()
        assert records == []
        mock_settings.is_wsl_running.assert_not_called()


class TestWslRunningCheck:
    """_query_wsl_running() must survive wsl.exe's UTF-16LE output."""

    @staticmethod
    def _fake_wsl(stdout_bytes: bytes) -> object:
        import subprocess as sp
        return sp.CompletedProcess(args=[], returncode=0, stdout=stdout_bytes)

    @pytest.mark.unit
    def test_running_distro_utf16_bom(self):
        from backend import config

        s = config.Settings()
        raw = b"\xff\xfe" + "  project-claude    Running    2\r\n".encode("utf-16-le")
        with patch.object(config.subprocess, "run", return_value=self._fake_wsl(raw)):
            assert s._query_wsl_running() is True

    @pytest.mark.unit
    def test_running_distro_utf16_without_bom(self):
        """zh-CN Windows emits UTF-16LE with no BOM and localized headers."""
        from backend import config

        s = config.Settings()
        raw = "适用于 Linux 的 Windows 子系统分发:\r\nproject-claude (默认)\r\n".encode("utf-16-le")
        with patch.object(config.subprocess, "run", return_value=self._fake_wsl(raw)):
            assert s._query_wsl_running() is True

    @pytest.mark.unit
    def test_no_running_distro_utf16(self):
        from backend import config

        s = config.Settings()
        raw = b"\xff\xfe" + "There are no running distributions.\r\n".encode("utf-16-le")
        with patch.object(config.subprocess, "run", return_value=self._fake_wsl(raw)):
            assert s._query_wsl_running() is False

    @pytest.mark.unit
    def test_no_running_distro_plain_ascii(self):
        """Defensive: some environments may emit plain ASCII/UTF-8."""
        from backend import config

        s = config.Settings()
        with patch.object(
            config.subprocess, "run",
            return_value=self._fake_wsl(b"There are no running distributions.\r\n"),
        ):
            assert s._query_wsl_running() is False

    @pytest.mark.unit
    def test_running_distro_plain_ascii(self):
        from backend import config

        s = config.Settings()
        with patch.object(
            config.subprocess, "run",
            return_value=self._fake_wsl(b"  project-claude    Running    2\r\n"),
        ):
            assert s._query_wsl_running() is True

    @pytest.mark.unit
    def test_other_distro_running_does_not_match(self):
        from backend import config

        s = config.Settings()
        raw = b"\xff\xfe" + "  ubuntu    Running    2\r\n".encode("utf-16-le")
        with patch.object(config.subprocess, "run", return_value=self._fake_wsl(raw)):
            assert s._query_wsl_running() is False

    @pytest.mark.unit
    def test_wsl_exe_missing(self):
        from backend import config

        s = config.Settings()
        with patch.object(config.subprocess, "run", side_effect=FileNotFoundError):
            assert s._query_wsl_running() is False


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


class TestQoderCollector:
    """Qoder run-log dumps + transcript compaction — shapes from Qoder 1.1.86."""

    SESSION_ID = "105b1459-2c08-4f7a-b9a2-367b55350152"
    UUID_WITH_USAGE = "550895cb-fdcb-496d-adbd-1046c51408b8"
    UUID_NO_USAGE = "df529bc2-879b-4e74-871f-83d40d9fb2d1"
    CWD = r"C:\Users\me\demo-project"

    # ── fixture builders (compact serialization, as in permission dumps) ──

    @staticmethod
    def _assistant_event(uuid: str, ts: str = "2026-11-23T05:48:10.642Z", usage: dict | None = None) -> str:
        msg: dict = {
            "id": "chatcmpl-6b03d35cbf689e852635f116",
            "type": "message",
            "role": "assistant",
            "model": "auto",
            "stop_reason": "tool_use" if usage is not None else None,
            "stop_sequence": None,
            "container": None,
            "context_management": None,
        }
        if usage is not None:
            msg["usage"] = usage
        msg["content"] = [{"type": "text", "text": "ok"}]
        event = {
            "type": "assistant",
            "uuid": uuid,
            "timestamp": ts,
            "message": msg,
            "requestId": "req-1",
            "responseGroupId": "grp-1",
            "requestTokenAnchor": {"request": "aa", "response": "bb", "requestId": "req-1"},
            "sessionId": TestQoderCollector.SESSION_ID,
            "session_id": TestQoderCollector.SESSION_ID,
        }
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _dump_line(events: list[str]) -> str:
        """One [permission-check] context line carrying the given events."""
        user = {
            "type": "user",
            "uuid": "b514aa50-7c47-49bc-a790-52d6ac5d9b2d",
            "timestamp": "2026-11-23T05:47:08.576Z",
            "message": {"role": "user", "content": "hi"},
            "businessModelKey": "kmodel-latest",
            "businessIdentity": {"product": "app"},
            "sessionId": TestQoderCollector.SESSION_ID,
        }
        body = '{"messages":[' + ",".join(
            [json.dumps(user, ensure_ascii=False, separators=(",", ":"))] + events
        ) + '],"agentId":"a1","scene":"tool"}'
        return (
            "2026-11-23T13:48:10.692+08:00 INFO  debug.message [permission-check] "
            f"context tool=Bash callId=1 agentId=a1 context={body}"
        )

    @staticmethod
    def _usage() -> dict:
        return {
            "input_tokens": 8474,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 7424,
            "output_tokens": 855,
        }

    @staticmethod
    def _transcript_runtime_config() -> str:
        return json.dumps({
            "type": "runtime-config",
            "sessionId": TestQoderCollector.SESSION_ID,
            "model": "kmodel-latest",
            "reasoningEffort": None,
            "contextWindow": None,
            "generation": None,
            "timestamp": 1795412737478,
        }, ensure_ascii=False)

    @staticmethod
    def _transcript_compact() -> str:
        return json.dumps({
            "type": "system",
            "uuid": "713ad13a-a7c1-48c9-9627-2cda6d39cc79",
            "timestamp": "2026-11-23T06:03:25.830Z",
            "subtype": "compact_boundary",
            "content": "Conversation compacted",
            "level": "info",
            "compactUsage": {
                "input_tokens": 164173,
                "output_tokens": 6240,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 162816,
                "credits": 7.78,
            },
            "modelRequestIds": ["5a204245"],
            "isSidechain": False,
            "cwd": TestQoderCollector.CWD,
            "sessionId": TestQoderCollector.SESSION_ID,
        }, ensure_ascii=False)

    @pytest.fixture
    def collector(self):
        return QoderCollector()

    @pytest.mark.unit
    def test_name(self, collector):
        assert collector.name == "qoder"

    @pytest.mark.asyncio
    async def test_collect_no_dir(self, collector, tmp_path):
        with (
            patch("backend.collectors.qoder._QODER_RUNS_DIR", tmp_path / "missing-runs"),
            patch("backend.collectors.qoder._QODER_PROJECTS_DIR", tmp_path / "missing-proj"),
        ):
            records = await collector.collect()
        assert records == []

    @pytest.mark.asyncio
    async def test_log_maps_fields(self, collector, tmp_path):
        log = tmp_path / "run-1" / "qodercli.log"
        log.parent.mkdir()
        # Two events: one with usage (counted), one without (skipped).
        line = self._dump_line([
            self._assistant_event(self.UUID_WITH_USAGE, usage=self._usage()),
            self._assistant_event(self.UUID_NO_USAGE),
        ])
        log.write_text(line + "\n", encoding="utf-8")

        with (
            patch("backend.collectors.qoder._QODER_RUNS_DIR", tmp_path),
            patch("backend.collectors.qoder._QODER_PROJECTS_DIR", tmp_path / "missing-proj"),
            patch.object(collector, "_load_state", return_value={
                "session_cwd": {self.SESSION_ID: self.CWD},
            }),
            patch.object(collector, "_save_state") as save_state,
        ):
            records = await collector.collect()

        assert len(records) == 1
        r = records[0]
        assert r.agent == "qoder"
        assert r.timestamp == "2026-11-23T05:48:10.642Z"
        # model "auto" falls back to the user event's businessModelKey
        assert r.model == "kmodel-latest"
        assert r.session_id == self.SESSION_ID
        # cache-inclusive input split: 8474 - 7424
        assert r.input_tokens == 1050
        assert r.output_tokens == 855
        assert r.cache_read_tokens == 7424
        assert r.cache_write_tokens == 0
        # project comes from the transcript-derived session_cwd map
        assert r.project == "demo-project"
        raw = json.loads(r.raw_data)
        assert raw["uuid"] == self.UUID_WITH_USAGE
        assert raw["source"] == "log-context"

        state = save_state.call_args[0][0]
        pos_key, pos_val = next(iter(state["log_positions"].items()))
        assert pos_key.endswith("qodercli.log")
        assert pos_val == log.stat().st_size

    @pytest.mark.asyncio
    async def test_log_dedupes_repeated_dump(self, collector, tmp_path):
        """The same response is re-dumped on every tool check — count it once."""
        log = tmp_path / "run-1" / "qodercli.log"
        log.parent.mkdir()
        line = self._dump_line([self._assistant_event(self.UUID_WITH_USAGE, usage=self._usage())])
        log.write_text(line + "\n" + line + "\n", encoding="utf-8")

        with (
            patch("backend.collectors.qoder._QODER_RUNS_DIR", tmp_path),
            patch("backend.collectors.qoder._QODER_PROJECTS_DIR", tmp_path / "missing-proj"),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state"),
        ):
            records = await collector.collect()

        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_zero_usage_skipped(self, collector, tmp_path):
        log = tmp_path / "run-1" / "qodercli.log"
        log.parent.mkdir()
        zero = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        }
        line = self._dump_line([self._assistant_event(self.UUID_WITH_USAGE, usage=zero)])
        log.write_text(line + "\n", encoding="utf-8")

        with (
            patch("backend.collectors.qoder._QODER_RUNS_DIR", tmp_path),
            patch("backend.collectors.qoder._QODER_PROJECTS_DIR", tmp_path / "missing-proj"),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state"),
        ):
            records = await collector.collect()

        assert records == []

    @pytest.mark.asyncio
    async def test_transcript_compact_record(self, collector, tmp_path):
        proj = tmp_path / "projects" / "demo"
        proj.mkdir(parents=True)
        f = proj / f"{self.SESSION_ID}.jsonl"
        f.write_text(
            self._transcript_runtime_config() + "\n"
            + json.dumps({"type": "user", "uuid": "u1", "sessionId": self.SESSION_ID,
                          "cwd": self.CWD, "timestamp": "2026-11-23T05:45:41.025Z"}) + "\n"
            + self._transcript_compact() + "\n",
            encoding="utf-8",
        )

        with (
            patch("backend.collectors.qoder._QODER_RUNS_DIR", tmp_path / "missing-runs"),
            patch("backend.collectors.qoder._QODER_PROJECTS_DIR", tmp_path / "projects"),
            patch.object(collector, "_load_state", return_value={}),
            patch.object(collector, "_save_state") as save_state,
        ):
            records = await collector.collect()

        assert len(records) == 1
        r = records[0]
        assert r.agent == "qoder"
        assert r.model == "kmodel-latest"
        assert r.timestamp == "2026-11-23T06:03:25.830Z"
        assert r.session_id == self.SESSION_ID
        assert r.project == "demo-project"
        # cache-inclusive input split: 164173 - 162816
        assert r.input_tokens == 1357
        assert r.output_tokens == 6240
        assert r.cache_read_tokens == 162816
        raw = json.loads(r.raw_data)
        assert raw["source"] == "compact"
        assert raw["credits"] == 7.78

        state = save_state.call_args[0][0]
        assert state["session_cwd"][self.SESSION_ID] == self.CWD
        ctx_key = next(iter(state["transcript_context"]))
        assert state["transcript_context"][ctx_key]["model"] == "kmodel-latest"
