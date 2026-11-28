"""user_version 2 → 3: openclaw cumulative snapshots → latest row per session."""

import aiosqlite
import pytest

from backend.db.data_migrations import migrate_openclaw_deltas
from backend.db.database import SCHEMA_SQL


async def _db_with_rows(tmp_path, rows):
    db = await aiosqlite.connect(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA_SQL)
    await db.executemany(
        """INSERT INTO token_usage
           (timestamp, agent, model, session_id, input_tokens, output_tokens,
            cache_read_tokens, cache_write_tokens, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_keeps_latest_snapshot_per_session_and_model(tmp_path):
    rows = [
        # sess-1: three cumulative snapshots — only the latest survives
        ("2026-05-01T10:00:00Z", "openclaw", "gpt-4o", "s1", 100, 10, 0, 0, 0.001),
        ("2026-05-01T11:00:00Z", "openclaw", "gpt-4o", "s1", 300, 30, 0, 0, 0.003),
        ("2026-05-01T12:00:00Z", "openclaw", "gpt-4o", "s1", 600, 60, 0, 0, 0.006),
        # same session, different model — kept independently
        ("2026-05-01T10:00:00Z", "openclaw", "glm-5.3", "s1", 50, 5, 0, 0, 0.0005),
        ("2026-05-01T11:00:00Z", "openclaw", "glm-5.3", "s1", 90, 9, 0, 0, 0.0009),
        # another session
        ("2026-05-01T10:00:00Z", "openclaw", "gpt-4o", "s2", 10, 1, 0, 0, 0.0001),
        # other agents untouched
        ("2026-05-01T10:00:00Z", "zcode", "gpt-4o", "s1", 7, 7, 0, 0, 0.0),
        ("2026-05-01T11:00:00Z", "zcode", "gpt-4o", "s1", 8, 8, 0, 0, 0.0),
    ]
    db = await _db_with_rows(tmp_path, rows)
    try:
        stats = await migrate_openclaw_deltas(db)
        await db.commit()
        assert stats["openclaw_rows_before"] == 6
        assert stats["openclaw_snapshots_dropped"] == 3

        kept = await db.execute_fetchall(
            "SELECT session_id, model, input_tokens FROM token_usage WHERE agent='openclaw' ORDER BY session_id, model"
        )
        assert [(r["session_id"], r["model"], r["input_tokens"]) for r in kept] == [
            ("s1", "glm-5.3", 90),
            ("s1", "gpt-4o", 600),
            ("s2", "gpt-4o", 10),
        ]
        # zcode rows with the same session id are not touched
        n = (await db.execute_fetchall("SELECT COUNT(*) AS n FROM token_usage WHERE agent='zcode'"))[0]["n"]
        assert n == 2

        # idempotent: a second run drops nothing
        stats2 = await migrate_openclaw_deltas(db)
        assert stats2["openclaw_snapshots_dropped"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_no_openclaw_rows_is_a_noop_without_backup(tmp_path):
    db = await _db_with_rows(tmp_path, [
        ("2026-05-01T10:00:00Z", "zcode", "gpt-4o", "s1", 7, 7, 0, 0, 0.0),
    ])
    try:
        stats = await migrate_openclaw_deltas(db)
        assert stats == {"openclaw_rows_before": 0, "openclaw_snapshots_dropped": 0}
        assert "backup" not in stats
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rows_without_session_id_are_left_alone(tmp_path):
    rows = [
        ("2026-05-01T10:00:00Z", "openclaw", "gpt-4o", "", 100, 10, 0, 0, 0.001),
        ("2026-05-01T11:00:00Z", "openclaw", "gpt-4o", "", 300, 30, 0, 0, 0.003),
    ]
    db = await _db_with_rows(tmp_path, rows)
    try:
        stats = await migrate_openclaw_deltas(db)
        assert stats["openclaw_rows_before"] == 0
        n = (await db.execute_fetchall("SELECT COUNT(*) AS n FROM token_usage"))[0]["n"]
        assert n == 2
    finally:
        await db.close()