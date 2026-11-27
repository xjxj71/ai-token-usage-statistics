"""Application version — single source of truth is ``pyproject.toml``.

Dev reads the repo root; frozen installs read the copy bundled into
``_internal`` (see ``build/tray_app.spec`` datas). Reading the file directly
avoids stale versions from editable-install metadata after a version bump.
"""

from __future__ import annotations

import logging
import tomllib
from functools import lru_cache

from backend import paths

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_app_version() -> str:
    for cand in (
        paths.bundle_root() / "pyproject.toml",
        paths.app_root() / "pyproject.toml",
    ):
        if cand.is_file():
            try:
                with open(cand, "rb") as f:
                    return str(tomllib.load(f)["project"]["version"])
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to read version from %s: %s", cand, exc)
    return "dev"