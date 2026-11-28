"""One-time data migrations (user_version 1 → 2 → 3).

v2: token semantics and pricing.

Rows written before this release break two conventions the rest of the app
sums by:

* **zcode** stored ZCode's ``input_tokens`` as-is, which is the *whole prompt*
  (cached tokens included) — ``totalTokens = inputTokens + outputTokens`` in
  the provider payload.  Costs therefore billed the cached part a second time
  at full price, and total tokens / cache ratio were skewed (real 30-day
  data: cost 4.5x too high, cache hit shown as 49% instead of 97.8%).
* **Hermes** rows were *cumulative session snapshots* — one per hour a session
  stayed open — so summing rows counted a session's tokens once per hour
  (3.4x on real data).

The migration rewrites those rows to the convention every collector now
writes: ``input_tokens`` is the cache-miss input, and every row is a true
increment.  It also brings pricing up to date: default prices that were
published as placeholders are replaced by the official ones *where the user
has not touched them*, and rows that were stored with no cost because their
model had no price yet are priced retroactively.

Safety: gated on ``PRAGMA user_version`` so it runs exactly once per
database; a copy of the database is taken first; costs are only recomputed
where the stored value is provably "tokens × price table" (never a cost the
source tool reported).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import settings
from backend.pricing.model_pricing import cost_from_prices, load_yaml_pricing

logger = logging.getLogger(__name__)

DATA_SCHEMA_VERSION = 3

ZCODE_AGENTS = ("zcode",)
HERMES_AGENTS = ("hermes", "hermes-win")
OPENCLAW_AGENTS = ("openclaw",)
# hanako stores the cost its provider reported (``usage.cost.total``).  A
# zero there can be a genuine zero, so it is never "backfilled" with a list
# price.
REPORTED_COST_AGENTS = ("hanako",)

# Default prices shipped before 2026-11-25 as "TBD" placeholders
# (input, output, cache_read, cache_write — USD per M tokens).  A pricing
# table row that still equals one of these was never edited by the user and
# is upgraded to the official price now in the YAML.
SUPERSEDED_DEFAULTS: dict[str, tuple[float, float, float, float]] = {
    "glm-5.3": (0.5, 2.0, 0.125, 0.0),
    "glm-5.1": (0.5, 2.0, 0.125, 0.0),
    "glm-5": (0.5, 2.0, 0.125, 0.0),
    "mimo-v2.6-pro": (0.8, 3.0, 0.2, 0.0),
}

# Stored costs are rounded to 6 decimals; anything within this of
# "tokens × old default" was calculated from that default.
_PRICE_MATCH_TOLERANCE = 1e-5

Price = dict[str, float]
Vector = tuple[float, float, float, float, float]  # input, output, cache_read, cache_write, cost


# ── Pricing table ─────────────────────────────────────────────────


def _in(prefix: str, values: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    """An ``IN (…)`` clause built from named bindings, plus the bindings.

    Returning the two together keeps every placeholder bound.
    """
    clause = ",".join(f":{prefix}{i}" for i in range(len(values)))
    return f"({clause})", {f"{prefix}{i}": v for i, v in enumerate(values)}


def _prices_of(row: Any) -> Price:
    return {
        "input": float(row["input_price"]),
        "output": float(row["output_price"]),
        "cache_read": float(row["cache_read_price"]),
        "cache_write": float(row["cache_write_price"]),
    }


async def _effective_pricing(db: aiosqlite.Connection) -> tuple[dict[str, Price], dict[str, int]]:
    """YAML defaults overlaid by the pricing table, after upgrading the
    pricing-table rows that still hold a superseded default."""
    yaml_pricing = load_yaml_pricing()
    stats = {"pricing_rows_upgraded": 0, "pricing_rows_kept": 0}

    clause, params = _in("m", tuple(SUPERSEDED_DEFAULTS))
    rows = await db.execute_fetchall(
        f"""SELECT model, input_price, output_price, cache_read_price, cache_write_price
           FROM model_pricing WHERE model IN {clause}""",
        params,
    )
    for row in rows:
        current = (
            float(row["input_price"]), float(row["output_price"]),
            float(row["cache_read_price"]), float(row["cache_write_price"]),
        )
        target = yaml_pricing.get(row["model"])
        if target is None or current != SUPERSEDED_DEFAULTS[row["model"]]:
            stats["pricing_rows_kept"] += 1
            continue
        await db.execute(
            """UPDATE model_pricing
               SET input_price = ?, output_price = ?, cache_read_price = ?, cache_write_price = ?,
                   updated_at = ?
               WHERE model = ?""",
            (
                target["input"], target["output"], target["cache_read"], target["cache_write"],
                datetime.now(UTC).isoformat(), row["model"],
            ),
        )
        stats["pricing_rows_upgraded"] += 1

    effective = {model: dict(p) for model, p in yaml_pricing.items()}
    # Rows that are still all zero were auto-inserted for models that had no
    # price yet.  With the pricing table now driving calculate_cost() they
    # would keep those models at $0 forever, so they take the YAML price.
    placeholders: list[tuple] = []
    for row in await db.execute_fetchall(
        "SELECT model, input_price, output_price, cache_read_price, cache_write_price FROM model_pricing"
    ):
        current = _prices_of(row)
        target = yaml_pricing.get(row["model"])
        if target and not any(current.values()) and any(target.values()):
            placeholders.append((
                target["input"], target["output"], target["cache_read"], target["cache_write"],
                datetime.now(UTC).isoformat(), row["model"],
            ))
            current = dict(target)
        effective[row["model"]] = current
    if placeholders:
        await db.executemany(
            """UPDATE model_pricing
               SET input_price = ?, output_price = ?, cache_read_price = ?, cache_write_price = ?,
                   updated_at = ?
               WHERE model = ?""",
            placeholders,
        )
    stats["pricing_placeholders_priced"] = len(placeholders)
    return effective, stats


# ── Cost rules ───────────────────────────────────────────────────


def _is_calculated_at(cost: float, tokens: tuple[int, int, int, int], prices: Price) -> bool:
    """True when ``cost`` is exactly ``tokens × prices`` — i.e. it was
    calculated from the price table rather than reported by the tool."""
    return abs(cost - cost_from_prices(prices, *tokens)) <= _PRICE_MATCH_TOLERANCE


async def _recalculate_costs(
    db: aiosqlite.Connection,
    table: str,
    effective: dict[str, Price],
    stats: dict[str, int],
) -> None:
    """Reprice rows of ``table`` (``token_usage`` or ``usage_daily``).

    A stored cost is replaced only when it is provably a price-table figure:

    * it is ``0`` although tokens were used (the model had no price when the
      row was written) — except for agents that report provider costs;
    * it equals ``tokens × superseded default`` for a model whose default
      was replaced by the official price;
    * it belongs to zcode in the archive table, whose tokens this migration
      just corrected (archived costs are always ``tokens × price table``).

    Everything else — in particular costs the source tool reported — is left
    exactly as it is.
    """
    is_usage = table == "token_usage"
    superseded, params = _in("m", tuple(SUPERSEDED_DEFAULTS))
    key_cols = "id" if is_usage else "date, agent, model, project"
    guards = zcode_clause = ""
    if not is_usage:
        # Archived zcode tokens were corrected above, so their costs follow …
        zcode_clause, z = _in("z", ZCODE_AGENTS)
        zcode_clause = f" OR agent IN {zcode_clause}"
        # … but archived Hermes rows keep snapshot-summed tokens that can no
        # longer be repaired, so their costs are not touched.
        hermes, h = _in("h", HERMES_AGENTS)
        guards = f" AND agent NOT IN {hermes}"
        params = {**params, **z, **h}

    rows = await db.execute_fetchall(
        f"""
        SELECT {key_cols}, agent, model, input_tokens, output_tokens,
               cache_read_tokens, cache_write_tokens, cost_usd
        FROM {table}
        WHERE (cost_usd = 0 OR model IN {superseded}{zcode_clause}){guards}
        """,
        params,
    )

    updates: list[tuple] = []
    for row in rows:
        tokens = (
            row["input_tokens"], row["output_tokens"],
            row["cache_read_tokens"], row["cache_write_tokens"],
        )
        cost = float(row["cost_usd"])
        prices = effective.get(row["model"])
        if not prices or not any(prices.values()):
            continue

        if cost == 0:
            if not any(tokens) or row["agent"] in REPORTED_COST_AGENTS:
                continue
            reason = "costs_backfilled"
        elif not is_usage and row["agent"] in ZCODE_AGENTS:
            reason = "costs_repriced"
        else:
            old = SUPERSEDED_DEFAULTS.get(row["model"])
            if old is None:
                continue
            old_prices = {
                "input": old[0], "output": old[1], "cache_read": old[2], "cache_write": old[3],
            }
            if not _is_calculated_at(cost, tokens, old_prices):
                continue
            reason = "costs_repriced"

        new_cost = cost_from_prices(prices, *tokens)
        if abs(new_cost - cost) <= _PRICE_MATCH_TOLERANCE:
            continue
        key = (row["id"],) if is_usage else (
            row["date"], row["agent"], row["model"], row["project"]
        )
        updates.append((new_cost, *key))
        stats[reason] = stats.get(reason, 0) + 1

    if not updates:
        return
    if is_usage:
        await db.executemany("UPDATE token_usage SET cost_usd = ? WHERE id = ?", updates)
    else:
        await db.executemany(
            """UPDATE usage_daily SET cost_usd = ?
               WHERE date = ? AND agent = ? AND model = ? AND project = ?""",
            updates,
        )


# ── Token semantics ──────────────────────────────────────────────


async def _fix_zcode(db: aiosqlite.Connection, effective: dict[str, Price]) -> int:
    """zcode: turn the whole-prompt figure into the cache-miss input."""
    agents, params = _in("a", ZCODE_AGENTS)
    cursor = await db.execute(
        f"""UPDATE token_usage
            SET input_tokens = MAX(input_tokens - cache_read_tokens - cache_write_tokens, 0)
            WHERE agent IN {agents} AND (cache_read_tokens > 0 OR cache_write_tokens > 0)""",
        params,
    )
    changed = cursor.rowcount or 0

    # zcode costs are always "tokens × price table", and the tokens just
    # changed, so they are recomputed outright.
    updates: list[tuple[float, int]] = []
    for row in await db.execute_fetchall(
        f"""SELECT id, model, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, cost_usd
            FROM token_usage
            WHERE agent IN {agents} AND cost_usd > 0""",
        params,
    ):
        prices = effective.get(row["model"])
        if not prices:
            continue
        new_cost = cost_from_prices(
            prices, row["input_tokens"], row["output_tokens"],
            row["cache_read_tokens"], row["cache_write_tokens"],
        )
        if abs(new_cost - float(row["cost_usd"])) > _PRICE_MATCH_TOLERANCE:
            updates.append((new_cost, row["id"]))
    if updates:
        await db.executemany("UPDATE token_usage SET cost_usd = ? WHERE id = ?", updates)
    return changed


def _ended(row: Any) -> bool:
    try:
        return json.loads(row["raw_data"] or "{}").get("ended") is True
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _values(row: Any) -> Vector:
    return (
        float(row["input_tokens"]), float(row["output_tokens"]),
        float(row["cache_read_tokens"]), float(row["cache_write_tokens"]),
        float(row["cost_usd"]),
    )


async def _fix_hermes(db: aiosqlite.Connection) -> dict[str, int]:
    """Hermes: cumulative snapshots → increments.

    A session that has its final (``ended``) row keeps exactly that row and
    drops the hourly snapshots it already includes.  A session still open has
    its snapshots turned into per-hour increments.  Rows above the final total
    belong to a session that was reopened later and continue from it.
    """
    agents, params = _in("a", HERMES_AGENTS)
    groups = await db.execute_fetchall(
        f"""SELECT agent, session_id, model
            FROM token_usage
            WHERE agent IN {agents} AND session_id != ''
            GROUP BY agent, session_id, model""",
        params,
    )

    deletes: list[int] = []
    updates: list[tuple] = []
    sessions_consolidated = 0

    for group in groups:
        rows = await db.execute_fetchall(
            """SELECT id, input_tokens, output_tokens, cache_read_tokens,
                      cache_write_tokens, cost_usd, raw_data
               FROM token_usage
               WHERE agent = ? AND session_id = ? AND model = ?
               ORDER BY timestamp, id""",
            (group["agent"], group["session_id"], group["model"]),
        )
        finals = [r for r in rows if _ended(r)]
        others = [r for r in rows if not _ended(r)]

        baseline: Vector | None = None
        if finals:
            keep = finals[-1]
            total = _values(keep)
            sessions_consolidated += 1
            baseline = total
            # Only the last final row is the session's total.
            deletes.extend(r["id"] for r in finals[:-1])
            # Snapshots taken before the session closed are covered by the
            # final row; anything larger came from a later reopening.
            pre_close = [
                r for r in others
                if all(v <= t for v, t in zip(_values(r)[:4], total[:4]))
            ]
            deletes.extend(r["id"] for r in pre_close)
            others = [r for r in others if r["id"] not in {p["id"] for p in pre_close}]

        if not others:
            continue

        # Hourly snapshots (or post-reopen snapshots) become increments of
        # the counter since the previous one — or since the final total.
        prev = baseline or (0.0, 0.0, 0.0, 0.0, 0.0)
        for row in others:
            cur = _values(row)
            delta = tuple(max(c - p, 0.0) for c, p in zip(cur, prev))
            updates.append((
                int(delta[0]), int(delta[1]), int(delta[2]), int(delta[3]),
                round(delta[4], 6), row["id"],
            ))
            prev = cur

    if deletes:
        await db.executemany(
            "DELETE FROM token_usage WHERE id = ?", [(i,) for i in deletes]
        )
    if updates:
        await db.executemany(
            """UPDATE token_usage
               SET input_tokens = ?, output_tokens = ?, cache_read_tokens = ?,
                   cache_write_tokens = ?, cost_usd = ?
               WHERE id = ?""",
            updates,
        )
    return {
        "hermes_sessions_consolidated": sessions_consolidated,
        "hermes_snapshots_dropped": len(deletes),
        "hermes_rows_deltaized": len(updates),
    }


async def _fix_usage_daily(db: aiosqlite.Connection) -> int:
    agents, params = _in("a", ZCODE_AGENTS)
    cursor = await db.execute(
        f"""UPDATE usage_daily
            SET input_tokens = MAX(input_tokens - cache_read_tokens - cache_write_tokens, 0)
            WHERE agent IN {agents} AND (cache_read_tokens > 0 OR cache_write_tokens > 0)""",
        params,
    )
    return cursor.rowcount or 0


# ── Backup / entry point ─────────────────────────────────────────


def _backup_path(version: int) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return settings.db_path.parent / "backups" / f"token_statistic_{stamp}_pre-v{version}.db"


def _sqlite_backup(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dst))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dst


async def migrate_token_semantics(db: aiosqlite.Connection) -> dict[str, Any]:
    """Normalise token semantics and pricing.  Call once, with
    ``PRAGMA user_version`` at 1; the caller bumps the version afterwards.
    """
    stats: dict[str, Any] = {}
    has_rows = (await db.execute_fetchall("SELECT 1 FROM token_usage LIMIT 1"))
    has_daily = (await db.execute_fetchall("SELECT 1 FROM usage_daily LIMIT 1"))
    if has_rows or has_daily:
        path = await asyncio.to_thread(_sqlite_backup, Path(settings.db_path), _backup_path(2))
        stats["backup"] = str(path)
        logger.info("Migration: pre-v2 database copy at %s", path)

    effective, pricing_stats = await _effective_pricing(db)
    stats.update(pricing_stats)

    if has_rows:
        stats["zcode_rows_fixed"] = await _fix_zcode(db, effective)
        stats.update(await _fix_hermes(db))
    if has_daily:
        stats["usage_daily_zcode_rows_fixed"] = await _fix_usage_daily(db)

    # Costs for rows whose tokens or prices changed above.
    if has_rows:
        await _recalculate_costs(db, "token_usage", effective, stats)
    if has_daily:
        hermes, params = _in("a", HERMES_AGENTS)
        hermes_daily = (await db.execute_fetchall(
            f"SELECT COUNT(*) AS n FROM usage_daily WHERE agent IN {hermes}", params
        ))[0]["n"]
        if hermes_daily:
            # Aggregated past the point where sessions can be told apart.
            logger.warning(
                "Migration: %d archived Hermes rows in usage_daily keep their "
                "snapshot-summed totals — the session detail needed to correct "
                "them was already pruned", hermes_daily,
            )
        await _recalculate_costs(db, "usage_daily", effective, stats)

    return stats


# ── user_version 2 → 3: openclaw snapshots → one row per session ─────


async def migrate_openclaw_deltas(db: aiosqlite.Connection) -> dict[str, Any]:
    """Consolidate pre-v3 openclaw rows (one-time, gated on user_version).

    The old collector wrote the session's **cumulative counters** as a new
    row on every ``updatedAt`` advance, so summing rows counted an active
    session's usage once per update (the bug class fixed for Hermes in v2).
    The counters at each snapshot are not recoverable as increments after
    the fact, so the best available approximation is the **latest snapshot
    per (session_id, model)** — the session's totals so far, same shape as
    a Hermes consolidated row.  The collector now writes true deltas.

    Rows without a session_id cannot be grouped and are left untouched.
    """
    stats: dict[str, Any] = {"openclaw_rows_before": 0, "openclaw_snapshots_dropped": 0}
    n = (await db.execute_fetchall(
        "SELECT COUNT(*) AS n FROM token_usage WHERE agent = 'openclaw' AND session_id != ''"
    ))[0]["n"]
    stats["openclaw_rows_before"] = n
    if not n:
        return stats

    path = await asyncio.to_thread(
        _sqlite_backup, Path(settings.db_path), _backup_path(DATA_SCHEMA_VERSION)
    )
    stats["backup"] = str(path)
    logger.info("Migration: pre-v%d database copy at %s", DATA_SCHEMA_VERSION, path)

    cur = await db.execute(
        """
        DELETE FROM token_usage
        WHERE agent = 'openclaw' AND session_id != '' AND id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY session_id, model
                    ORDER BY timestamp DESC, id DESC
                ) AS rn
                FROM token_usage
                WHERE agent = 'openclaw' AND session_id != ''
            ) WHERE rn = 1
        )
        """
    )
    stats["openclaw_snapshots_dropped"] = cur.rowcount or 0
    return stats
