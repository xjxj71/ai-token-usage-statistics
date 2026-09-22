"""Shared SQLite helpers for collectors that read live source databases.

Sources like the Hermes state.db or the ZCode usage db are written by another
process, often in WAL mode, while we poll them. Reading the original file
directly risks lock contention and mid-transaction snapshots; copying the main
db plus its ``-wal``/``-shm`` sidecars to a temp file first gives us a stable
private snapshot (SQLite recovers the WAL into the copy on open).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from backend import paths

logger = logging.getLogger(__name__)


def remove_sqlite_temp(tmp_path: str) -> None:
    """Remove a temp db snapshot created by :func:`copy_sqlite_with_wal`."""
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(tmp_path + suffix).unlink(missing_ok=True)
        except OSError:
            pass


def copy_sqlite_with_wal(db_path: str | Path) -> str | None:
    """Copy a SQLite database (main file + WAL/SHM sidecars) to a temp file.

    Blocking — call via ``asyncio.to_thread``. Returns the temp path, or
    None if the copy failed (caller should skip this poll).
    """
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".db", dir=str(paths.temp_dir()))
        os.close(fd)
        shutil.copy2(db_path, tmp_path)
        # Copy WAL and SHM sidecar files if they exist
        for suffix in ("-wal", "-shm"):
            src_sidecar = str(db_path) + suffix
            if Path(src_sidecar).exists():
                shutil.copy2(src_sidecar, tmp_path + suffix)
        return tmp_path
    except OSError as e:
        logger.warning("Failed to copy sqlite db %s: %s", db_path, e)
        return None
