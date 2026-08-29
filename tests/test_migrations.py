"""Tests for schema migrations on databases created by older releases."""

import json
import sqlite3

import pytest

from backend.db import database as db_module
from backend.db.models import TokenRecord, insert_records, project_from_cwd

# Schema as of v0.4.0 — before project/reasoning_tokens columns existed.
OLD_SCHEMA = """
CREATE TABLE token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    agent             TEXT NOT NULL,
    model             TEXT NOT NULL,
    session_id        TEXT,
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_read_tokens  INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    cost_usd          REAL DEFAULT 0.0,
    raw_data          TEXT
);
"""

_OLD_INSERT = (
    "INSERT INTO token_usage (timestamp, agent, model, session_id,"
    " input_tokens, output_tokens, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def _create_old_db(db_file, rows):
    conn = sqlite3.connect(db_file)
    conn.executescript(OLD_SCHEMA)
    conn.executemany(_OLD_INSERT, rows)
    conn.commit()
    conn.close()


# ── project_from_cwd unit tests ──────────────────────────────────


class TestProjectFromCwd:
    @pytest.mark.unit
    def test_unix_path(self):
        assert project_from_cwd("/home/claude/projects/my-repo") == "my-repo"

    @pytest.mark.unit
    def test_windows_path(self):
        assert project_from_cwd("D:\\research project\\ai-token-usage-statistics") == "ai-token-usage-statistics"

    @pytest.mark.unit
    def test_trailing_separators(self):
        assert project_from_cwd("/home/user/repo/") == "repo"
        assert project_from_cwd("C:\\work\\repo\\\\") == "repo"

    @pytest.mark.unit
    def test_unc_path(self):
        assert project_from_cwd("\\\\wsl$\\project-claude\\home\\claude\\repo") == "repo"

    @pytest.mark.unit
    def test_drive_root(self):
        assert project_from_cwd("D:\\") == "D:"

    @pytest.mark.unit
    def test_empty_inputs(self):
        assert project_from_cwd("") == ""
        assert project_from_cwd(None) == ""
        assert project_from_cwd("///") == ""


# ── Migration tests ──────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_init_db_upgrades_old_schema_and_backfills(tmp_path, monkeypatch):
    """A pre-migration database gains new columns and gets raw_data backfilled."""
    from backend import config

    db_file = tmp_path / "old.db"
    _create_old_db(
        db_file,
        [
            # zcode-style: snake_case cwd + reasoning_tokens
            (
                "2026-05-01T10:00:00Z", "zcode", "glm-5.3", "s1", 100, 200,
                json.dumps({"cwd": "/home/user/repo-a", "reasoning_tokens": 42}),
            ),
            # claude-code style: Windows cwd, no reasoning
            (
                "2026-05-01T11:00:00Z", "claude-code", "claude-sonnet-4-6", "s2", 300, 400,
                json.dumps({"cwd": "D:\\work\\repo-b\\", "gitBranch": "main"}),
            ),
            # hermes style: no cwd/reasoning at all
            (
                "2026-05-01T12:00:00Z", "hermes", "gpt-4o", "s3", 500, 600,
                json.dumps({"_row_id": 7, "ended": True}),
            ),
            # corrupt raw_data must not break the migration
            (
                "2026-05-01T13:00:00Z", "hermes", "gpt-4o", "s4", 700, 800,
                "{not json",
            ),
        ],
    )

    monkeypatch.setattr(config.settings, "db_path", db_file)
    await db_module.close_db()
    await db_module.init_db()

    db = await db_module.get_db()

    # Columns added
    cols = {r["name"] for r in await db.execute_fetchall("PRAGMA table_info(token_usage)")}
    assert "project" in cols
    assert "reasoning_tokens" in cols

    # Session index + usage_daily table created
    indexes = {
        r["name"]
        for r in await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='token_usage'"
        )
    }
    assert "idx_token_usage_session" in indexes
    tables = {
        r["name"]
        for r in await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "usage_daily" in tables

    # Backfilled values
    rows = await db.execute_fetchall(
        "SELECT agent, project, reasoning_tokens FROM token_usage ORDER BY id"
    )
    assert (rows[0]["agent"], rows[0]["project"], rows[0]["reasoning_tokens"]) == ("zcode", "repo-a", 42)
    assert (rows[1]["agent"], rows[1]["project"], rows[1]["reasoning_tokens"]) == ("claude-code", "repo-b", 0)
    assert (rows[2]["agent"], rows[2]["project"], rows[2]["reasoning_tokens"]) == ("hermes", "", 0)
    # Corrupt row left at defaults, not dropped
    assert (rows[3]["agent"], rows[3]["project"], rows[3]["reasoning_tokens"]) == ("hermes", "", 0)

    # user_version bumped so the backfill never runs twice
    version = (await db.execute_fetchall("PRAGMA user_version"))[0]["user_version"]
    assert version == 1

    await db_module.close_db()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_init_db_migration_idempotent(tmp_path, monkeypatch):
    """Re-running init_db on an already-migrated database changes nothing."""
    from backend import config

    db_file = tmp_path / "old.db"
    _create_old_db(
        db_file,
        [
            (
                "2026-05-01T10:00:00Z", "zcode", "glm-5.3", "s1", 100, 200,
                json.dumps({"cwd": "/home/user/repo-a", "reasoning_tokens": 42}),
            ),
        ],
    )

    monkeypatch.setattr(config.settings, "db_path", db_file)
    await db_module.close_db()
    await db_module.init_db()

    # Simulate a user editing the project column after migration — a second
    # init must not overwrite it with the raw_data-derived value again.
    db = await db_module.get_db()
    await db.execute("UPDATE token_usage SET project = 'renamed'")
    await db.commit()
    await db_module.close_db()

    await db_module.init_db()
    db = await db_module.get_db()
    rows = await db.execute_fetchall("SELECT project FROM token_usage")
    assert rows[0]["project"] == "renamed"

    await db_module.close_db()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_insert_records_writes_new_columns(client):
    """New records written through insert_records carry project/reasoning."""
    db = await db_module.get_db()
    await insert_records(
        db,
        [
            TokenRecord(
                timestamp="2026-05-02T10:00:00Z",
                agent="zcode",
                model="glm-5.3",
                session_id="s1",
                project="demo",
                input_tokens=100,
                output_tokens=200,
                reasoning_tokens=50,
            )
        ],
    )
    rows = await db.execute_fetchall("SELECT project, reasoning_tokens FROM token_usage")
    assert rows[0]["project"] == "demo"
    assert rows[0]["reasoning_tokens"] == 50
