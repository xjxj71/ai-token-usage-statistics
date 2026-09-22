"""Filesystem layout helpers for dev, installed (frozen), and portable modes.

All writable paths must go through this module so PyInstaller builds do not
depend on the process CWD or on ``__file__`` depth inside ``_internal``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_APP_DIR_NAME = "ai-token-usage"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def portable_mode() -> bool:
    return (app_root() / "portable.flag").is_file()


def app_root() -> Path:
    """Install root (frozen) or repository root (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # backend/paths.py -> backend -> repo root
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """PyInstaller resource root (onedir ``_internal`` or app root)."""
    return Path(getattr(sys, "_MEIPASS", app_root()))


def _user_base() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    return Path.home() / "AppData" / "Roaming"


def data_dir() -> Path:
    if is_frozen() and not portable_mode():
        return _user_base() / _APP_DIR_NAME / "data"
    return app_root() / "data"


def config_dir() -> Path:
    if is_frozen() and not portable_mode():
        return _user_base() / _APP_DIR_NAME / "config"
    return app_root() / "config"


def frontend_dist() -> Path:
    candidates = (
        bundle_root() / "frontend" / "dist",
        app_root() / "frontend" / "dist",
    )
    for cand in candidates:
        if cand.is_dir():
            return cand
    return candidates[0]


def temp_dir() -> Path:
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        return Path(tmp)
    return Path(tempfile.gettempdir())


def instance_state_path() -> Path:
    return data_dir() / "instance.json"


def backups_dir() -> Path:
    return data_dir() / "backups"


def db_path() -> Path:
    return data_dir() / "token_statistic.db"


def collector_state_path() -> Path:
    return data_dir() / "collector_state.json"


def app_log_path() -> Path:
    return data_dir() / "app.log"


def quota_providers_path() -> Path:
    return config_dir() / "quota_providers.yaml"


def model_pricing_yaml_path() -> Path:
    """Read-only pricing seed: bundled template first, then user config."""
    bundled = bundle_root() / "config" / "model_pricing.yaml"
    if bundled.is_file():
        return bundled
    user = config_dir() / "model_pricing.yaml"
    if user.is_file():
        return user
    return app_root() / "config" / "model_pricing.yaml"


def env_file_path() -> Path:
    return config_dir() / ".env"


def collector_temp_prefix(agent: str) -> Path:
    """Temp path prefix for collector DB copies (stays out of install dir)."""
    return temp_dir() / f"ai-token-usage-{agent}"


def init_user_dirs() -> None:
    """Create writable dirs and seed config templates without overwriting."""
    data_dir().mkdir(parents=True, exist_ok=True)
    backups_dir().mkdir(parents=True, exist_ok=True)
    config_dir().mkdir(parents=True, exist_ok=True)

    dest = quota_providers_path()
    if not dest.exists():
        for src in (
            bundle_root() / "config" / "quota_providers.example.yaml",
            app_root() / "config" / "quota_providers.example.yaml",
        ):
            if src.is_file():
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                break
