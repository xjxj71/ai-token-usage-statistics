# MimoCode & OpenCode Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add token usage collectors for MimoCode and OpenCode AI coding agents, which store session data in SQLite databases.

**Architecture:** Create a shared SQLite parsing utility (`opencode_db_utils.py`) and two collector classes that extend `BaseCollector`. Both agents use the same database schema (MiMoCode is a fork of OpenCode), so the core parsing logic is shared.

**Tech Stack:** Python 3.11+, aiosqlite, SQLite, Pydantic

---

## File Structure

```
backend/collectors/
├── opencode_db_utils.py    # NEW: Shared SQLite parsing for OpenCode-family DBs
├── mimo_code.py            # NEW: MimoCodeCollector
├── open_code.py            # NEW: OpenCodeCollector
└── registry.py             # MODIFY: Register new collectors
```

---

### Task 1: Create Shared SQLite Parsing Utility

**Covers:** Core data extraction logic for OpenCode-family databases

**Files:**
- Create: `backend/collectors/opencode_db_utils.py`

- [ ] **Step 1: Create the shared utility module**

```python
"""Shared SQLite parsing utilities for OpenCode-family collectors.

MiMoCode and OpenCode use the same database schema (MiMoCode is a fork of OpenCode).
Token usage data is stored in the `message` table as JSON in the `data` field.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.db.models import TokenRecord
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


def _parse_timestamp_ms(ts_ms: int | None) -> str:
    """Convert millisecond epoch timestamp to ISO format string."""
    if not ts_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, OSError):
        return ""


def extract_token_records(
    db_path: str | Path,
    agent_name: str,
    last_timestamp_ms: int = 0,
) -> tuple[Sequence[TokenRecord], int]:
    """Extract token usage records from an OpenCode-family SQLite database.

    Args:
        db_path: Path to the SQLite database file
        agent_name: Agent name to set on records (e.g., "mimo-code", "opencode")
        last_timestamp_ms: Only process messages after this timestamp (ms epoch)

    Returns:
        (records, max_timestamp_ms) - List of TokenRecord and the latest timestamp seen
    """
    import sqlite3

    db_path = Path(db_path)
    if not db_path.exists():
        logger.debug("%s: database not found at %s", agent_name, db_path)
        return [], last_timestamp_ms

    records: list[TokenRecord] = []
    max_ts_ms = last_timestamp_ms

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query assistant messages with token usage data
        query = """
            SELECT id, session_id, time_created, data
            FROM message
            WHERE data LIKE '%"role":"assistant"%'
              AND data LIKE '%"tokens"%'
              AND time_created > ?
            ORDER BY time_created ASC
        """

        cursor.execute(query, (last_timestamp_ms,))
        rows = cursor.fetchall()

        for row in rows:
            try:
                data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Only process assistant messages
            if data.get("role") != "assistant":
                continue

            tokens = data.get("tokens")
            if not tokens:
                continue

            # Extract token counts
            input_tokens = tokens.get("input", 0) or 0
            output_tokens = tokens.get("output", 0) or 0
            reasoning_tokens = tokens.get("reasoning", 0) or 0
            cache = tokens.get("cache", {})
            cache_read = cache.get("read", 0) or 0
            cache_write = cache.get("write", 0) or 0

            # Skip all-zero records
            if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
                continue

            # Extract model info
            model_id = data.get("modelID", "unknown")
            provider_id = data.get("providerID", "")
            model = f"{provider_id}/{model_id}" if provider_id and model_id != "unknown" else model_id

            # Extract timestamp
            time_data = data.get("time", {})
            created_ms = time_data.get("created", row["time_created"])
            timestamp = _parse_timestamp_ms(created_ms)

            if not timestamp:
                continue

            # Calculate cost
            cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)

            # Build raw metadata
            raw_data = json.dumps({
                "session_id": row["session_id"],
                "message_id": row["id"],
                "provider_id": provider_id,
                "model_id": model_id,
                "reasoning_tokens": reasoning_tokens,
            }, ensure_ascii=False)

            record = TokenRecord(
                timestamp=timestamp,
                agent=agent_name,
                model=model.lower(),
                session_id=row["session_id"] or "",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=round(cost, 6),
                raw_data=raw_data,
            )
            records.append(record)

            # Track max timestamp
            if created_ms and created_ms > max_ts_ms:
                max_ts_ms = created_ms

        conn.close()

    except sqlite3.Error as e:
        logger.error("%s: database error: %s", agent_name, e)
        return [], last_timestamp_ms

    logger.info("%s: extracted %d records from database", agent_name, len(records))
    return records, max_ts_ms
```

- [ ] **Step 2: Verify syntax**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -c "from backend.collectors.opencode_db_utils import extract_token_records; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/collectors/opencode_db_utils.py
git commit -m "feat: add shared SQLite parsing utility for OpenCode-family collectors"
```

---

### Task 2: Create MimoCode Collector

**Covers:** MimoCode agent token usage collection

**Files:**
- Create: `backend/collectors/mimo_code.py`

- [ ] **Step 1: Create the MimoCodeCollector class**

```python
"""MimoCode token usage collector.

Reads token usage from MiMoCode's SQLite database at ~/.local/share/mimocode/mimocode.db.
MiMoCode is a fork of OpenCode, so it shares the same database schema.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.opencode_db_utils import extract_token_records
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)

# Default database path for MiMoCode
_MIMOCODE_DB_PATH = Path.home() / ".local" / "share" / "mimocode" / "mimocode.db"


class MimoCodeCollector(BaseCollector):
    """Collect token usage from MiMoCode SQLite database."""

    @property
    def name(self) -> str:
        return "mimo-code"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_ms = state.get("last_timestamp_ms", 0)

        records, new_max_ts = extract_token_records(
            db_path=_MIMOCODE_DB_PATH,
            agent_name=self.name,
            last_timestamp_ms=last_ts_ms,
        )

        # Persist watermark
        self._save_state({"last_timestamp_ms": new_max_ts})

        logger.info("MimoCode: collected %d new records", len(records))
        return records
```

- [ ] **Step 2: Verify syntax**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -c "from backend.collectors.mimo_code import MimoCodeCollector; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/collectors/mimo_code.py
git commit -m "feat: add MimoCode token usage collector"
```

---

### Task 3: Create OpenCode Collector

**Covers:** OpenCode agent token usage collection

**Files:**
- Create: `backend/collectors/open_code.py`

- [ ] **Step 1: Create the OpenCodeCollector class**

```python
"""OpenCode token usage collector.

Reads token usage from OpenCode's SQLite database at ~/.local/share/opencode/opencode.db.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from backend.collectors.base import BaseCollector
from backend.collectors.opencode_db_utils import extract_token_records
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)

# Default database path for OpenCode
_OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


class OpenCodeCollector(BaseCollector):
    """Collect token usage from OpenCode SQLite database."""

    @property
    def name(self) -> str:
        return "opencode"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()
        last_ts_ms = state.get("last_timestamp_ms", 0)

        records, new_max_ts = extract_token_records(
            db_path=_OPENCODE_DB_PATH,
            agent_name=self.name,
            last_timestamp_ms=last_ts_ms,
        )

        # Persist watermark
        self._save_state({"last_timestamp_ms": new_max_ts})

        logger.info("OpenCode: collected %d new records", len(records))
        return records
```

- [ ] **Step 2: Verify syntax**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -c "from backend.collectors.open_code import OpenCodeCollector; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/collectors/open_code.py
git commit -m "feat: add OpenCode token usage collector"
```

---

### Task 4: Register Collectors in Registry

**Covers:** Integration with the polling system

**Files:**
- Modify: `backend/collectors/registry.py:8-13` (imports)
- Modify: `backend/collectors/registry.py:31-38` (COLLECTORS list)

- [ ] **Step 1: Add imports**

Add after line 13 (`from backend.collectors.openclaw import OpenClawCollector`):

```python
from backend.collectors.mimo_code import MimoCodeCollector
from backend.collectors.open_code import OpenCodeCollector
```

- [ ] **Step 2: Register collectors in COLLECTORS list**

Add to the `COLLECTORS` list (after `OpenClaudeCollector()`):

```python
MimoCodeCollector(),
OpenCodeCollector(),
```

The final COLLECTORS list should be:

```python
COLLECTORS: list[BaseCollector] = [
    ClaudeCodeCollector(),
    HanakoCollector(),
    HermesCollector(),
    HermesWindowsCollector(),
    OpenClawCollector(),
    OpenClaudeCollector(),
    MimoCodeCollector(),
    OpenCodeCollector(),
]
```

- [ ] **Step 3: Verify imports**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -c "from backend.collectors.registry import COLLECTORS; print([c.name for c in COLLECTORS])"`
Expected: `['claude-code', 'hanako', 'hermes', 'hermes-win', 'openclaw', 'openclaw', 'mimo-code', 'opencode']`

- [ ] **Step 4: Commit**

```bash
git add backend/collectors/registry.py
git commit -m "feat: register MimoCode and OpenCode collectors in registry"
```

---

### Task 5: Run Existing Tests

**Covers:** Verify no regressions

**Files:** None (test execution only)

- [ ] **Step 1: Run pytest**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -m pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Run ruff linter**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -m ruff check backend/collectors/opencode_db_utils.py backend/collectors/mimo_code.py backend/collectors/open_code.py`
Expected: No errors

---

### Task 6: Manual Integration Test

**Covers:** End-to-end verification with real databases

**Files:** None (manual verification)

- [ ] **Step 1: Test collection from real databases**

Run: `cd "D:\research project\ai-token-usage-statistics" && python -c "
import asyncio
from backend.collectors.mimo_code import MimoCodeCollector
from backend.collectors.open_code import OpenCodeCollector

async def test():
    mimo = MimoCodeCollector()
    records = await mimo.collect()
    print(f'MimoCode: {len(records)} records')
    if records:
        print(f'  Sample: {records[0].agent} / {records[0].model} / {records[0].input_tokens} input')
    
    opencode = OpenCodeCollector()
    records = await opencode.collect()
    print(f'OpenCode: {len(records)} records')
    if records:
        print(f'  Sample: {records[0].agent} / {records[0].model} / {records[0].input_tokens} input')

asyncio.run(test())
"`
Expected: Shows record counts and sample data from both databases
