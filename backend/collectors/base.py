from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Sequence

from backend.config import settings
from backend.db.models import TokenRecord


class BaseCollector(ABC):
    # Subclasses set True to use UPSERT (insert-or-update) instead of INSERT OR IGNORE.
    # Used by collectors that track cumulative session-level data which updates over time.
    upsert_mode: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def collect(self) -> Sequence[TokenRecord]:
        ...

    def _load_state(self) -> dict:
        path = settings.collector_state_path
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get(self.name, {})
        return {}

    def _save_state(self, state: dict) -> None:
        path = settings.collector_state_path
        path.parent.mkdir(parents=True, exist_ok=True)

        all_state: dict = {}
        if path.exists():
            all_state = json.loads(path.read_text(encoding="utf-8"))

        all_state[self.name] = state
        content = json.dumps(all_state, indent=2, ensure_ascii=False)

        # Atomic write: write to a temp file in the same directory, then replace.
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=".collector_state_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _wsl_path(self, relative: str) -> str:
        win_path = relative.replace("/", "\\")
        return f"{settings.wsl_root}\\{win_path}"
