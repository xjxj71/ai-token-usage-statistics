from __future__ import annotations

import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Sequence

from backend.config import settings
from backend.db.models import TokenRecord

logger = logging.getLogger(__name__)


def _read_state_file() -> dict:
    """Read the shared collector state file, tolerating missing/corrupt JSON.

    A corrupt state file must not crash every collector on every poll —
    treat it as empty and let the next _save_state replace it.
    """
    path = settings.collector_state_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Collector state file unreadable, resetting: %s (%s)", path, e)
        return {}
    return data if isinstance(data, dict) else {}


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
        data = _read_state_file().get(self.name, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict) -> None:
        path = settings.collector_state_path
        path.parent.mkdir(parents=True, exist_ok=True)

        all_state = _read_state_file()
        all_state[self.name] = state
        content = json.dumps(all_state, indent=2, ensure_ascii=False)

        # Atomic write with stale-tmp cleanup.
        #
        # Concurrency risk: if multiple writers race, one .tmp can be
        # left behind when a second writer reads-and-replaces the first.
        # We defensively remove stale .tmp files owned by this collector
        # before creating the new one, so no orphan .tmp can mislead a
        # future reader into loading partial JSON.
        prefix = f".collector_state_{self.name}_"
        try:
            for stale in path.parent.glob(f"{prefix}*.tmp"):
                try:
                    stale.unlink()
                except OSError:
                    pass
        except OSError:
            pass

        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=prefix, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _wsl_path(self, relative: str) -> str:
        win_path = relative.replace("/", "\\")
        return f"{settings.wsl_root}\\{win_path}"
