#!/usr/bin/env python3
"""Recalculate cost_usd for all token_usage records based on model_pricing.yaml.

Usage:
    python scripts/recalc_costs.py [--dry-run] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.pricing.model_pricing import load_pricing, MODEL_PRICING


def recalc(db_path: str, dry_run: bool = False) -> None:
    pricing = load_pricing()
    if not pricing:
        print("ERROR: No pricing data loaded from YAML!")
        sys.exit(1)

    print(f"Loaded pricing for {len(pricing)} models")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Fetch all records
    rows = conn.execute(
        """SELECT id, model, input_tokens, output_tokens,
                  cache_read_tokens, cache_write_tokens, cost_usd
           FROM token_usage
           ORDER BY id"""
    ).fetchall()

    print(f"Total records: {len(rows)}")

    updated = 0
    unchanged = 0
    skipped_no_pricing = 0
    total_old_cost = 0.0
    total_new_cost = 0.0
    unknown_models: set[str] = set()

    updates: list[tuple[float, int]] = []

    for row in rows:
        model = row["model"]
        p = pricing.get(model)

        if p is None:
            unknown_models.add(model)
            skipped_no_pricing += 1
            total_old_cost += row["cost_usd"]
            total_new_cost += row["cost_usd"]  # unchanged
            continue

        new_cost = round(
            (
                row["input_tokens"] * p["input"]
                + row["output_tokens"] * p["output"]
                + row["cache_read_tokens"] * p.get("cache_read", 0)
                + row["cache_write_tokens"] * p.get("cache_write", 0)
            )
            / 1_000_000,
            6,
        )

        old_cost = row["cost_usd"]
        total_old_cost += old_cost
        total_new_cost += new_cost

        if abs(new_cost - old_cost) > 1e-9:
            updates.append((new_cost, row["id"]))
            updated += 1
        else:
            unchanged += 1

    print()
    print(f"Records to update: {updated}")
    print(f"Records unchanged: {unchanged}")
    print(f"Records skipped (no pricing): {skipped_no_pricing}")
    if unknown_models:
        print(f"  Unknown models: {', '.join(sorted(unknown_models))}")
    print()
    print(f"Total old cost: ${total_old_cost:,.6f}")
    print(f"Total new cost: ${total_new_cost:,.6f}")
    print(f"Delta:          ${total_new_cost - total_old_cost:+,.6f}")

    if dry_run:
        print()
        print("DRY RUN - no changes written to database")
    elif updates:
        print()
        conn.executemany("UPDATE token_usage SET cost_usd = ? WHERE id = ?", updates)
        conn.commit()
        print(f"Successfully updated {updated} records in database")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Recalculate token_usage costs from YAML pricing")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing to DB")
    parser.add_argument("--db", default=str(_PROJECT_ROOT / "data" / "token_statistic.db"),
                        help="Path to SQLite database")
    args = parser.parse_args()
    recalc(args.db, args.dry_run)


if __name__ == "__main__":
    main()
