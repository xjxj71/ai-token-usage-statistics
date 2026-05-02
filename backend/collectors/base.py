from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from backend.config import settings
from backend.db.models import TokenRecord


class BaseCollector(ABC):
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
        path.write_text(json.dumps(all_state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _wsl_path(self, relative: str) -> str:
        win_path = relative.replace("/", "\\")
        return f"{settings.wsl_root}\\{win_path}"
