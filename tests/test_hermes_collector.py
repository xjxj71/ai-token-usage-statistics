"""Hermes collector: cumulative session counters → summable increment rows.

Hermes' state.db keeps cumulative per-session counters.  The collector must
turn them into rows that can be summed like every other agent's (summing the
old hourly snapshots counted a session's tokens once per hour it stayed
open), and it must stay idempotent:

* re-polling rewrites the same absolute values instead of adding to them;
* a closed session collapses to one row holding the totals straight from
  state.db, which also heals whatever the hourly rows looked like.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest

from backend.collectors.hermes import HermesCollector
from backend.db.database import SCHEMA_SQL
from backend.db.models import TokenRecord, upsert_records
from backend.pricing.model_pricing import MODEL_PRICING, cost_from_prices

MODEL = "gpt-4o"
H10 = "2026-11-25T10:00:00+00:00"
H11 = "2026-11-25T11:00:00+00:00"


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 25, hour, minute, tzinfo=UTC)


def _write_state_db(path: Path, sessions: list[dict]) -> None:
    path.unlink(missing_ok=True)          # always rebuild from scratch
    conn = sqlite_connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, input_tokens INTEGER, output_tokens INTEGER,
            cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            estimated_cost_usd REAL, actual_cost_usd REAL,
            started_at INTEGER, ended_at INTEGER, model TEXT
        );
        """
    )
    for s in sessions:
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s["id"], s.get("input", 0), s.get("output", 0), s.get("cache_read", 0),
                s.get("cache_write", 0), None, s.get("actual_cost"),
                s["started_at"], s.get("ended_at"), s.get("model", MODEL),
            ),
        )
    conn.commit()
    conn.close()


def sqlite_connect(path: Path):
    import sqlite3

    return sqlite3.connect(path)


async def _poll(collector: HermesCollector, db_path: Path, state: dict, now: datetime):
    """Run one poll with the clock frozen at ``now``."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    with patch("backend.collectors.hermes.datetime", _Frozen):
        return await collector._read_sessions(str(db_path), state)


async def _memory_db():
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA_SQL)
    return db


def _shape(records):
    return [
        (r.timestamp, r.input_tokens, r.output_tokens, r.cache_read_tokens) for r in records
    ]


@pytest.mark.asyncio
async def test_open_session_writes_hourly_increments_then_consolidates(tmp_path):
    db_path = tmp_path / "state.db"
    started = int(_at(10, 1).timestamp())
    price = MODEL_PRICING[MODEL]

    def write(inp: int, out: int, cache: int, ended: int | None = None) -> None:
        _write_state_db(
            db_path,
            [{"id": "s1", "started_at": started, "ended_at": ended,
              "input": inp, "output": out, "cache_read": cache}],
        )

    collector = HermesCollector()
    state = {"last_poll_at": _at(10, 0).isoformat()}

    # 10:05 — created after the previous poll, so counted from zero.
    write(100, 10, 1000)
    records, state = await _poll(collector, db_path, state, _at(10, 5))
    assert _shape(records) == [(H10, 100, 10, 1000)]
    assert records[0].replace_session is False
    assert records[0].cost_usd == pytest.approx(cost_from_prices(price, 100, 10, 1000))

    # 10:30 — same hour: the row is rewritten with the hour's total, not added to.
    write(250, 25, 2400)
    records, state = await _poll(collector, db_path, state, _at(10, 30))
    assert _shape(records) == [(H10, 250, 25, 2400)]

    # 11:10 — a new hour: the earlier hour is final, the new one holds only
    # its own usage.
    write(400, 40, 3900)
    records, state = await _poll(collector, db_path, state, _at(11, 10))
    assert _shape(records) == [(H10, 250, 25, 2400), (H11, 150, 15, 1500)]
    hourly = records

    # Nothing moved → nothing written.
    records, _ = await _poll(collector, db_path, state, _at(11, 20))
    assert records == []

    # The session closes: one row with the session total replaces the hourly rows.
    write(450, 45, 4300, ended=started + 5000)
    records, state = await _poll(collector, db_path, state, _at(11, 40))
    assert _shape(records) == [(H10, 450, 45, 4300)]
    assert records[0].replace_session is True
    assert "s1" not in state["session_marks"]
    assert "s1" in state["finalized_ids"]

    db = await _memory_db()
    try:
        await upsert_records(db, hourly)
        assert len(await db.execute_fetchall("SELECT id FROM token_usage")) == 2
        await upsert_records(db, records)
        rows = await db.execute_fetchall(
            "SELECT input_tokens, output_tokens, cache_read_tokens, cost_usd FROM token_usage"
        )
        assert [(r[0], r[1], r[2]) for r in rows] == [(450, 45, 4300)]
        assert rows[0][3] == pytest.approx(cost_from_prices(price, 450, 45, 4300))
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rows_are_absolute_hour_totals_across_app_restarts(tmp_path):
    """The hour row is derived from state, not incremented in place: after a
    restart (state reloaded from JSON) a later poll in the same hour still
    writes the hour's total, and an unchanged poll writes nothing."""
    import json

    db_path = tmp_path / "state.db"
    started = int(_at(10, 1).timestamp())

    def write(inp: int) -> None:
        _write_state_db(db_path, [{"id": "s1", "started_at": started, "input": inp}])

    collector = HermesCollector()
    state = {"last_poll_at": _at(10, 0).isoformat()}

    write(400)
    records, state = await _poll(collector, db_path, state, _at(11, 10))
    assert _shape(records) == [(H11, 400, 0, 0)]

    # Same counters → no write at all.
    unchanged, state = await _poll(collector, db_path, state, _at(11, 15))
    assert unchanged == []

    # Process restart: state comes back from disk as plain JSON.
    reloaded = json.loads(json.dumps(state))
    write(700)
    records, _ = await _poll(collector, db_path, reloaded, _at(11, 40))
    assert _shape(records) == [(H11, 700, 0, 0)]        # not 400 + 700


@pytest.mark.asyncio
async def test_identical_upsert_is_a_noop_for_change_tracking():
    """Re-upserting identical values must not count as a change: Hermes
    re-emits an open session's earlier hour rows on every poll, and SSE
    notifications are driven by ``db.total_changes``.  A ``raw_data``-only
    difference (the ``last_seen`` stamp, which has no readers) must be
    skipped too, so an idle hour row causes no WAL write."""
    from dataclasses import replace

    db = await _memory_db()
    try:
        rec = TokenRecord(
            timestamp=H10, agent="hermes", model=MODEL, session_id="s1",
            input_tokens=100, output_tokens=10, cache_read_tokens=900,
            cost_usd=0.01, raw_data='{"last_seen": "t1"}',
        )
        await upsert_records(db, [rec])
        baseline = db.total_changes

        await upsert_records(db, [replace(rec, raw_data='{"last_seen": "t2"}')])
        assert db.total_changes == baseline

        await upsert_records(db, [replace(rec, input_tokens=150)])
        assert db.total_changes == baseline + 1
        rows = await db.execute_fetchall("SELECT input_tokens FROM token_usage")
        assert rows[0][0] == 150
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_closed_session_heals_after_state_loss(tmp_path):
    """Losing the state file must not double count: a closed session is
    rewritten from state.db's own totals over whatever rows exist."""
    db_path = tmp_path / "state.db"
    started = int(_at(10, 1).timestamp())
    _write_state_db(
        db_path,
        [{"id": "s1", "started_at": started, "ended_at": started + 5000,
          "input": 450, "output": 45, "cache_read": 4300}],
    )
    collector = HermesCollector()
    records, _ = await _poll(collector, db_path, {}, _at(12, 0))

    db = await _memory_db()
    try:
        # Hourly increments left over from before the state was lost.
        await upsert_records(db, [
            TokenRecord(timestamp=H10, agent="hermes", model=MODEL, session_id="s1",
                        input_tokens=250, output_tokens=25, cache_read_tokens=2400),
            TokenRecord(timestamp=H11, agent="hermes", model=MODEL, session_id="s1",
                        input_tokens=150, output_tokens=15, cache_read_tokens=1500),
        ])
        await upsert_records(db, records)
        rows = await db.execute_fetchall(
            "SELECT input_tokens, output_tokens, cache_read_tokens FROM token_usage"
        )
        assert [(r[0], r[1], r[2]) for r in rows] == [(450, 45, 4300)]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_pre_existing_open_session_is_seeded_not_dumped(tmp_path):
    """An open session first seen with usage from before we watched it starts
    from its current counters; only later usage is written."""
    db_path = tmp_path / "state.db"
    started = int(_at(8, 0).timestamp())

    def write(inp: int) -> None:
        _write_state_db(
            db_path, [{"id": "old", "started_at": started, "input": inp}]
        )

    collector = HermesCollector()
    write(1000)
    records, state = await _poll(collector, db_path, {}, _at(10, 5))
    assert records == []

    write(1200)
    records, _ = await _poll(collector, db_path, state, _at(10, 20))
    assert _shape(records) == [(H10, 200, 0, 0)]


@pytest.mark.asyncio
async def test_reopened_session_continues_from_its_final_total(tmp_path):
    """A closed-then-reopened session keeps its final row and adds later
    usage as new increments on top of it."""
    db_path = tmp_path / "state.db"
    started = int(_at(10, 1).timestamp())
    closed = started + 5000

    def write(inp: int, ended: int | None) -> None:
        _write_state_db(
            db_path, [{"id": "s1", "started_at": started, "ended_at": ended, "input": inp}]
        )

    collector = HermesCollector()
    write(450, closed)
    records, state = await _poll(collector, db_path, {}, _at(12, 0))
    assert _shape(records) == [(H10, 450, 0, 0)]

    # Reopened (ended_at cleared) with more usage since.
    write(700, None)
    records, state = await _poll(collector, db_path, state, _at(13, 5))
    assert records == []           # seeded at the current counters
    write(800, None)
    records, _ = await _poll(collector, db_path, state, _at(13, 20))
    assert _shape(records) == [("2026-11-25T13:00:00+00:00", 100, 0, 0)]
    assert "s1" not in state["finalized_ids"]


@pytest.mark.asyncio
async def test_failed_query_leaves_state_untouched(tmp_path):
    db_path = tmp_path / "state.db"
    db_path.write_bytes(b"not a database")
    collector = HermesCollector()
    state = {"closed_up_to_rowid": 7, "finalized_ids": ["x"]}
    records, returned = await _poll(collector, db_path, state, _at(12, 0))
    assert records == []
    assert returned is state
