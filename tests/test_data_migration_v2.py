"""user_version 1 → 2: normalise token semantics and pricing in existing data.

The migration rewrites history, so every rule it applies — and everything it
must leave alone — is pinned down here.
"""

import json
import sqlite3

import pytest

from backend import config
from backend.db import database as db_module
from backend.db.data_migrations import DATA_SCHEMA_VERSION
from backend.db.database import SCHEMA_SQL
from backend.pricing.model_pricing import (
    MODEL_PRICING,
    clear_pricing_overlay,
    cost_from_prices,
    load_pricing,
)

# Prices as the previous release seeded them.
GLM_OLD = {"input": 0.5, "output": 2.0, "cache_read": 0.125, "cache_write": 0.0}
GLM_NEW = {"input": 1.4, "output": 4.4, "cache_read": 0.26, "cache_write": 0.0}
GLM_CUSTOM = {"input": 9.9, "output": 9.9, "cache_read": 0.5, "cache_write": 0.0}
GPT = {"input": 2.5, "output": 10.0, "cache_read": 1.25, "cache_write": 0.0}
SONNET = {"input": 3.0, "output": 15.0, "cache_read": 0.375, "cache_write": 0.0}

USAGE_SQL = (
    "INSERT INTO token_usage (timestamp, agent, model, session_id, project, input_tokens,"
    " output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, cost_usd,"
    " raw_data) VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)"
)
DAILY_SQL = (
    "INSERT INTO usage_daily (date, agent, model, project, input_tokens, output_tokens,"
    " cache_read_tokens, cache_write_tokens, reasoning_tokens, cost_usd, call_count)"
    " VALUES (?, ?, ?, '', ?, ?, ?, ?, 0, ?, 1)"
)
PRICING_SQL = (
    "INSERT INTO model_pricing (model, input_price, output_price, cache_read_price,"
    " cache_write_price, updated_at) VALUES (?, ?, ?, ?, ?, '2026-01-01')"
)


def _hermes(ts, sid, tokens, ended, cost):
    return (
        ts, "hermes-win", "gpt-4o", sid, tokens[0], tokens[1], tokens[2], 0, 0, cost,
        json.dumps({"_row_id": 1, "ended": ended}),
    )


def _create_v1_db(db_file, usage, daily=(), pricing=()):
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)
    conn.executemany(USAGE_SQL, usage)
    conn.executemany(DAILY_SQL, daily)
    conn.executemany(PRICING_SQL, pricing)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def _row(tokens, cost, model="glm-5.3"):
    return (tokens[0], tokens[1], tokens[2], tokens[3], cost, model)


def _seed_pricing_rows():
    return [
        ("glm-5.3", GLM_OLD["input"], GLM_OLD["output"], GLM_OLD["cache_read"], 0.0),
        ("glm-5.1", GLM_CUSTOM["input"], GLM_CUSTOM["output"], GLM_CUSTOM["cache_read"], 0.0),
        ("gpt-4o", GPT["input"], GPT["output"], GPT["cache_read"], 0.0),
        ("claude-sonnet-4-6", SONNET["input"], SONNET["output"], SONNET["cache_read"], 0.0),
    ]


async def _rows(sql):
    db = await db_module.get_db()
    return [tuple(r) for r in await db.execute_fetchall(sql)]


@pytest.fixture
def v1_db(tmp_path, monkeypatch):
    """A database as the previous release left it, before init_db()."""
    async def setup(usage, daily=(), pricing=None):
        db_file = tmp_path / "token_statistic.db"
        _create_v1_db(db_file, usage, daily, _seed_pricing_rows() if pricing is None else pricing)
        monkeypatch.setattr(config.settings, "db_path", db_file)
        await db_module.close_db()
        return db_file

    return setup


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_normalises_tokens_snapshots_and_pricing(v1_db, tmp_path):
    c_gpt = lambda *t: cost_from_prices(GPT, *t)
    usage = [
        # zcode: whole-prompt figure billed at the old default price
        ("2026-11-20T10:00:00Z", "zcode", "glm-5.3", "z1", 10000, 500, 4000, 500, 0,
         cost_from_prices(GLM_OLD, 10000, 500, 4000, 500), "{}"),
        # other agents already stored the cache-miss input
        ("2026-11-20T11:00:00Z", "claude-code", "claude-sonnet-4-6", "c1", 1000, 500, 2000, 0, 0,
         cost_from_prices(SONNET, 1000, 500, 2000), "{}"),
        # a price-table figure at the superseded default → repriced
        ("2026-11-20T12:00:00Z", "claude-code", "glm-5.3", "c2", 1000, 100, 0, 0, 0,
         cost_from_prices(GLM_OLD, 1000, 100), "{}"),
        # no price when it was written → backfilled
        ("2026-11-20T13:00:00Z", "zcode", "glm-5.4", "z2", 100, 0, 0, 0, 0, 0.0, "{}"),
        # hanako reports what the provider charged: a zero stays a zero …
        ("2026-11-20T14:00:00Z", "hanako", "glm-5.3", "h1", 1000, 100, 0, 0, 0, 0.0, "{}"),
        # … and a reported cost is never replaced by a list-price estimate
        ("2026-11-20T15:00:00Z", "openclaw", "glm-5.3", "o1", 1000, 100, 0, 0, 0, 0.123456, "{}"),
        # unpriced model stays unpriced
        ("2026-11-20T16:00:00Z", "qoder", "kmodel_latest", "q1", 100, 10, 0, 0, 0, 0.0, "{}"),
        # Hermes closed session: final row + the hourly snapshots it includes
        _hermes("2026-11-20T09:00:00Z", "hc", (100, 10, 1000, 0), False, c_gpt(100, 10, 1000)),
        _hermes("2026-11-20T10:00:00Z", "hc", (250, 25, 2400, 0), False, c_gpt(250, 25, 2400)),
        _hermes("2026-11-20T08:00:00Z", "hc", (450, 45, 4300, 0), True, c_gpt(450, 45, 4300)),
        # Hermes session still open: cumulative hourly snapshots
        _hermes("2026-11-20T09:00:00Z", "ho", (100, 10, 1000, 0), False, c_gpt(100, 10, 1000)),
        _hermes("2026-11-20T10:00:00Z", "ho", (250, 25, 2400, 0), False, c_gpt(250, 25, 2400)),
        _hermes("2026-11-20T11:00:00Z", "ho", (400, 40, 3900, 0), False, c_gpt(400, 40, 3900)),
    ]
    daily = [
        ("2026-10-01", "zcode", "glm-5.3", 10000, 500, 4000, 0, 0.006),
        ("2026-10-01", "claude-code", "glm-5.3", 1000, 100, 0, 0, cost_from_prices(GLM_OLD, 1000, 100)),
        ("2026-10-01", "hanako", "glm-5.3", 1000, 100, 0, 0, 0.0),
        ("2026-10-01", "hermes-win", "gpt-4o", 750, 75, 7300, 0, 0.5),
    ]
    await v1_db(usage, daily)

    await db_module.init_db()

    by_key = {
        (r[0], r[1]): r for r in await _rows(
            "SELECT agent, session_id, input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, cost_usd, model FROM token_usage"
        )
    }

    # zcode: cache-miss input only, cost recomputed from the corrected tokens.
    z = by_key[("zcode", "z1")]
    assert z[2:6] == (5500, 500, 4000, 500)
    assert z[6] == pytest.approx(cost_from_prices(GLM_NEW, 5500, 500, 4000, 500))

    # Untouched agent.
    c = by_key[("claude-code", "c1")]
    assert c[2:6] == (1000, 500, 2000, 0)
    assert c[6] == pytest.approx(cost_from_prices(SONNET, 1000, 500, 2000))

    # Repriced from the superseded default to the official price.
    assert by_key[("claude-code", "c2")][6] == pytest.approx(cost_from_prices(GLM_NEW, 1000, 100))

    # Backfilled now that glm-5.4 has a price.
    assert by_key[("zcode", "z2")][6] == pytest.approx(cost_from_prices(GLM_NEW, 100, 0))

    # Provider-reported zeros and costs are left alone; unpriced stays 0.
    assert by_key[("hanako", "h1")][6] == 0.0
    assert by_key[("openclaw", "o1")][6] == 0.123456
    assert by_key[("qoder", "q1")][6] == 0.0

    # Closed Hermes session: exactly one row, the final total.
    assert [k for k in by_key if k[1] == "hc"] == [("hermes-win", "hc")]
    assert by_key[("hermes-win", "hc")][2:5] == (450, 45, 4300)
    assert by_key[("hermes-win", "hc")][6] == pytest.approx(c_gpt(450, 45, 4300))

    # Open Hermes session: cumulative snapshots became per-hour increments
    # whose sum is still the running total.
    ho = sorted(
        (r for r in await _rows(
            "SELECT timestamp, input_tokens, output_tokens, cache_read_tokens, cost_usd"
            " FROM token_usage WHERE session_id = 'ho'"
        )),
        key=lambda r: r[0],
    )
    assert [r[1:4] for r in ho] == [(100, 10, 1000), (150, 15, 1400), (150, 15, 1500)]
    assert sum(r[4] for r in ho) == pytest.approx(c_gpt(400, 40, 3900))

    # Archive table: zcode tokens/cost follow, defaults are repriced, the
    # reported zero stays, archived Hermes rows are left as they are.
    daily_rows = {
        r[0:2]: r for r in await _rows(
            "SELECT agent, model, input_tokens, cost_usd FROM usage_daily ORDER BY agent"
        )
    }
    assert daily_rows[("zcode", "glm-5.3")][2] == 6000
    assert daily_rows[("zcode", "glm-5.3")][3] == pytest.approx(
        cost_from_prices(GLM_NEW, 6000, 500, 4000)
    )
    assert daily_rows[("claude-code", "glm-5.3")][3] == pytest.approx(
        cost_from_prices(GLM_NEW, 1000, 100)
    )
    assert daily_rows[("hanako", "glm-5.3")][3] == 0.0
    assert daily_rows[("hermes-win", "gpt-4o")][2:4] == (750, 0.5)

    # Pricing table: the untouched default moved to the official price, the
    # user's own price did not, and the table is what calculate_cost() uses.
    table = {
        r[0]: r[1:] for r in await _rows(
            "SELECT model, input_price, output_price, cache_read_price FROM model_pricing"
        )
    }
    assert table["glm-5.3"] == (1.4, 4.4, 0.26)
    assert table["glm-5.1"] == (9.9, 9.9, 0.5)
    assert "glm-5.4" in table                                   # seeded from the new YAML
    assert MODEL_PRICING["glm-5.1"]["input"] == 9.9
    assert MODEL_PRICING["glm-5.3"]["input"] == 1.4

    # A copy of the pre-migration database was kept, holding the old values.
    backups = list((tmp_path / "backups").glob("*_pre-v2.db"))
    assert len(backups) == 1
    old = sqlite3.connect(backups[0])
    try:
        assert old.execute(
            "SELECT input_tokens FROM token_usage WHERE session_id = 'z1'"
        ).fetchone()[0] == 10000
        assert old.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        old.close()

    assert (await _rows("PRAGMA user_version"))[0][0] == DATA_SCHEMA_VERSION


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_runs_once(v1_db, tmp_path):
    usage = [
        ("2026-11-20T10:00:00Z", "zcode", "glm-5.3", "z1", 10000, 500, 4000, 0, 0,
         cost_from_prices(GLM_OLD, 10000, 500, 4000), "{}"),
        _hermes("2026-11-20T09:00:00Z", "ho", (100, 10, 1000, 0), False, 0.01),
        _hermes("2026-11-20T10:00:00Z", "ho", (250, 25, 2400, 0), False, 0.02),
    ]
    await v1_db(usage)

    await db_module.init_db()
    first = await _rows(
        "SELECT session_id, timestamp, input_tokens, cost_usd FROM token_usage ORDER BY id"
    )
    await db_module.close_db()

    await db_module.init_db()
    await db_module.close_db()

    db = sqlite3.connect(tmp_path / "token_statistic.db")
    try:
        again = [tuple(r) for r in db.execute(
            "SELECT session_id, timestamp, input_tokens, cost_usd FROM token_usage ORDER BY id"
        )]
    finally:
        db.close()
    assert again == first
    # zcode was converted exactly once (not 6000 → 2000).
    assert [r[2] for r in again if r[0] == "z1"] == [6000]
    assert [r[2] for r in again if r[0] == "ho"] == [100, 150]
    assert len(list((tmp_path / "backups").glob("*_pre-v2.db"))) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fresh_database_needs_no_backup(tmp_path, monkeypatch):
    db_file = tmp_path / "fresh.db"
    monkeypatch.setattr(config.settings, "db_path", db_file)
    await db_module.close_db()
    await db_module.init_db()
    assert (await _rows("PRAGMA user_version"))[0][0] == DATA_SCHEMA_VERSION
    assert not (tmp_path / "backups").exists()
    # Seeded rows map model → its own price (an INSERT with the columns in the
    # wrong order once stored prices in the model column).
    table = {r[0]: r[1:4] for r in await _rows(
        "SELECT model, input_price, output_price, cache_read_price FROM model_pricing"
    )}
    assert table["glm-5.3"] == (1.4, 4.4, 0.26)
    assert table["glm-5.4"] == (1.4, 4.4, 0.26)
    assert table["openrouter/free"] == (0.0, 0.0, 0.0)
    assert len(table) == len({m for m in table}) == 64


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_placeholder_rows_take_the_yaml_price(v1_db):
    """A model that first showed up before it had a price got an all-zero
    pricing row.  Once the YAML has a price, that row follows it and the
    rows stored without a cost are priced — but a non-zero row the user set
    is never touched."""
    usage = [
        ("2026-11-20T10:00:00Z", "zcode", "glm-5.4", "z1", 1000, 0, 0, 0, 0, 0.0, "{}"),
        ("2026-11-20T11:00:00Z", "claude-code", "glm-5.2", "c1", 1000, 100, 0, 0, 0, 0.0, "{}"),
        ("2026-11-20T12:00:00Z", "claude-code", "glm-5-turbo", "c2", 1000, 100, 0, 0, 0, 0.0, "{}"),
    ]
    await v1_db(usage, pricing=[
        *_seed_pricing_rows(),
        ("glm-5.4", 0.0, 0.0, 0.0, 0.0),            # auto-inserted placeholder
        ("glm-5.2", 0.0, 0.0, 0.0, 0.0),            # auto-inserted placeholder
        ("glm-5-turbo", 0.25, 0.9, 0.07, 0.0),      # the user's own price
    ])

    await db_module.init_db()

    table = {
        r[0]: r[1:] for r in await _rows(
            "SELECT model, input_price, output_price, cache_read_price FROM model_pricing"
        )
    }
    assert table["glm-5.4"] == (1.4, 4.4, 0.26)
    assert table["glm-5.2"] == (1.4, 4.4, 0.26)
    assert table["glm-5-turbo"] == (0.25, 0.9, 0.07)

    costs = {r[0]: r[1] for r in await _rows(
        "SELECT session_id, cost_usd FROM token_usage"
    )}
    assert costs["z1"] == pytest.approx(cost_from_prices(GLM_NEW, 1000, 0))
    assert costs["c1"] == pytest.approx(cost_from_prices(GLM_NEW, 1000, 100))
    # Not a placeholder, and the row was never priced by the table.
    assert costs["c2"] == pytest.approx(cost_from_prices(
        {"input": 0.25, "output": 0.9, "cache_read": 0.07, "cache_write": 0.0}, 1000, 100
    ))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reopened_session_keeps_its_total_and_later_increments(v1_db):
    """A session closed, then reopened: rows above the final total are later
    usage and continue from it instead of being dropped."""
    c = lambda *t: cost_from_prices(GPT, *t)
    usage = [
        _hermes("2026-11-20T09:00:00Z", "s", (100, 10, 1000, 0), False, c(100, 10, 1000)),
        _hermes("2026-11-20T08:00:00Z", "s", (450, 45, 4300, 0), True, c(450, 45, 4300)),
        _hermes("2026-11-20T13:00:00Z", "s", (600, 60, 5000, 0), False, c(600, 60, 5000)),
    ]
    await v1_db(usage)

    await db_module.init_db()

    rows = sorted(
        await _rows(
            "SELECT timestamp, input_tokens, cache_read_tokens FROM token_usage ORDER BY timestamp"
        ),
        key=lambda r: r[0],
    )
    assert rows == [
        ("2026-11-20T08:00:00Z", 450, 4300),      # the earlier closure's total
        ("2026-11-20T13:00:00Z", 150, 700),       # usage since reopening
    ]


# ── Pricing overlay ─────────────────────────────────────────────


@pytest.mark.unit
def test_overlay_makes_the_pricing_table_the_runtime_truth():
    try:
        load_pricing()
        assert MODEL_PRICING["glm-5.1"]["input"] == 1.4
        overlay = {"glm-5.1": {"input": 7.0, "output": 7.0, "cache_read": 0.0, "cache_write": 0.0}}
        from backend.pricing.model_pricing import overlay_pricing

        overlay_pricing(overlay)
        assert MODEL_PRICING["glm-5.1"]["input"] == 7.0
        # Reloading the YAML keeps the user's table in effect.
        load_pricing()
        assert MODEL_PRICING["glm-5.1"]["input"] == 7.0
    finally:
        clear_pricing_overlay()
    assert MODEL_PRICING["glm-5.1"]["input"] == 1.4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_editing_a_price_applies_to_new_records(client):
    from backend.pricing.model_pricing import calculate_cost

    before = calculate_cost("glm-5.3", 1_000_000, 0)
    res = await client.put("/api/pricing/glm-5.3", json={"input_price": 7.0, "output_price": 7.0})
    assert res.status_code == 200
    assert calculate_cost("glm-5.3", 1_000_000, 0) == pytest.approx(7.0)
    assert before != pytest.approx(7.0)
