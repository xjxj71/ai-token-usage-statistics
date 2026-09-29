from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from pydantic import Field, PrivateAttr
from pydantic_settings import BaseSettings

from backend import paths

logger = logging.getLogger(__name__)

# How long is_wsl_running() trusts its cached answer. Short enough that a
# distro start/stop is noticed within one poll cycle, long enough that the
# WSL-dependent collectors and their helpers share one wsl.exe query.
_WSL_RUNNING_TTL = 2.0

# Windowed (tray/noconsole) builds must not flash a console for wsl.exe.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def _run_quiet(cmd: list[str], **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.update(_NO_WINDOW)
    return subprocess.run(cmd, check=False, **kwargs)


class Settings(BaseSettings):
    wsl_distro: str = "project-claude"

    # WSL user whose home dir is accessible via UNC (claude = default WSL user)
    wsl_user_accessible: str = "claude"
    # WSL user whose files need root copy (hermes/openclaw run as root)
    wsl_user_root: str = "root"

    db_path: Path = Field(default_factory=paths.db_path)
    collector_state_path: Path = Field(default_factory=paths.collector_state_path)

    poll_interval_seconds: int = 5
    host: str = "127.0.0.1"
    port: int = 8001

    # Optional API key for authentication. If empty, auth is disabled.
    api_key: str = ""

    # CORS allowed origins. Comma-separated list. Default only allows the
    # local Vite dev server; set TOKEN_STAT_CORS_ORIGINS="*" (not recommended,
    # effectively allows any site with credentials) or a real domain in prod.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Exchange rate for USD to CNY display (configurable).
    usd_to_cny_rate: float = 7.25

    frontend_dist: Path = Field(default_factory=paths.frontend_dist)

    model_config = {
        "env_prefix": "TOKEN_STAT_",
        "env_file": str(paths.env_file_path()),
        "extra": "ignore",
    }

    # (monotonic_time, result) cache for is_wsl_running()
    _wsl_running_cache: tuple[float, bool] | None = PrivateAttr(default=None)

    @property
    def is_wsl(self) -> bool:
        """True if currently running inside WSL."""
        try:
            import platform
            return "microsoft" in platform.uname().release.lower()
        except Exception:  # noqa: BLE001
            return False

    @property
    def wsl_root(self) -> str:
        """UNC prefix: \\\\wsl$\\<distro>"""
        return f"\\\\wsl$\\{self.wsl_distro}"

    # ── Data source paths ────────────────────────────────────
    # When running inside WSL, return Linux native paths directly.
    # When running on Windows, return UNC paths.

    @property
    def hermes_db_path(self) -> str:
        """Hermes state.db — copied to /tmp for access."""
        if self.is_wsl:
            return "/tmp/hermes_state.db"
        return f"{self.wsl_root}\\tmp\\hermes_state.db"

    @property
    def hermes_win_db_path(self) -> str:
        """Windows native Hermes state.db path.

        Returns the standard ``%LOCALAPPDATA%\\hermes\\state.db`` path.
        Empty string if LOCALAPPDATA is not set (non-Windows).
        """
        local = os.environ.get("LOCALAPPDATA", "")
        if not local:
            return ""
        return os.path.join(local, "hermes", "state.db")

    @property
    def zcode_db_path(self) -> str:
        """ZCode CLI usage database (~/.zcode/cli/db/db.sqlite).

        ZCode records one row per model request in its ``model_usage``
        table — read passively, no hooks needed.
        """
        return str(Path.home() / ".zcode" / "cli" / "db" / "db.sqlite")

    @property
    def claude_projects_dir(self) -> str:
        """Claude Code session JSONL directory (~/.claude/projects/).

        Zero-intrusion data source: Claude Code writes session files here
        natively. We read them directly — no hooks or config needed.
        """
        if self.is_wsl:
            return f"/home/{self.wsl_user_accessible}/.claude/projects"
        return f"{self.wsl_root}\\home\\{self.wsl_user_accessible}\\.claude\\projects"

    @property
    def openclaw_sessions_path(self) -> str:
        """OpenClaw sessions.json — copied to /tmp for access."""
        if self.is_wsl:
            return "/tmp/openclaw_sessions.json"
        return f"{self.wsl_root}\\tmp\\openclaw_sessions.json"

    # ── WSL running-state check ──────────────────────────────

    def is_wsl_running(self) -> bool:
        """True if the target WSL distro is currently running.

        This never starts the distro: ``wsl.exe --list --running`` only
        reports state, unlike ``wsl.exe -d <distro> -- ...`` or touching
        ``\\\\wsl$\\<distro>`` paths, both of which boot a stopped distro.

        The answer is cached for ``_WSL_RUNNING_TTL`` seconds so the
        WSL-dependent collectors don't spawn wsl.exe several times per
        poll cycle.
        """
        if self.is_wsl:
            return True
        now = time.monotonic()
        cached = self._wsl_running_cache
        if cached is not None and now - cached[0] < _WSL_RUNNING_TTL:
            return cached[1]
        running = self._query_wsl_running()
        self._wsl_running_cache = (now, running)
        return running

    def _query_wsl_running(self) -> bool:
        """Ask wsl.exe which distros are running and look for ours.

        wsl.exe localizes its output and emits UTF-16LE — with or without
        a BOM depending on the Windows version/locale (observed BOM-less
        on zh-CN Windows), so ``text=True`` (ANSI code page) garbles it
        and even BOM-sniffing is unreliable.  Decode both ways and search
        each: the distro name only survives in the correct decode.
        """
        try:
            result = _run_quiet(
                ["wsl.exe", "--list", "--running"],
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.debug("wsl.exe --list --running failed: %s", e)
            return False
        raw = result.stdout or b""
        texts = (
            raw.decode("utf-16-le", errors="replace"),
            raw.decode("utf-8", errors="replace"),
        )
        return any(self.wsl_distro in t.replace("\x00", "") for t in texts)

    # ── Permission fix helper ────────────────────────────────

    def ensure_claude_projects_readable(self) -> None:
        """Fix permissions on Claude Code project files owned by root.

        When Claude Code runs as root (e.g. via sudo), it creates session
        JSONL files under ``~claude/.claude/projects/`` owned by root with
        mode 600.  The Windows UNC reader accesses these as the WSL default
        user (claude), which gets Permission denied.

        This method chowns and chmods the tree so the default user can read.
        Inside WSL we are already root — direct chmod/chown.
        On Windows we call ``wsl.exe -u root`` to do it.
        """
        linux_dir = f"/home/{self.wsl_user_accessible}/.claude/projects"
        try:
            if self.is_wsl:
                import os
                import pwd
                target_uid = pwd.getpwnam(self.wsl_user_accessible).pw_uid
                # Walk and fix ownership + readability
                for dirpath, _dirnames, filenames in os.walk(linux_dir):
                    try:
                        os.chown(dirpath, target_uid, target_uid)
                        os.chmod(dirpath, 0o755)
                    except OSError:
                        pass
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        try:
                            os.chown(fp, target_uid, target_uid)
                            os.chmod(fp, 0o644)
                        except OSError:
                            pass
                return

            # Windows: call wsl.exe to fix permissions as root
            if not self.is_wsl_running():
                logger.debug(
                    "WSL distro '%s' not running, skipping permission fix",
                    self.wsl_distro,
                )
                return
            safe_user = shlex.quote(self.wsl_user_accessible)
            safe_dir = shlex.quote(linux_dir)
            result = _run_quiet(
                [
                    "wsl.exe", "-u", self.wsl_user_root, "-d", self.wsl_distro, "--",
                    "bash", "-c",
                    (f"chown -R {safe_user}:{safe_user} {safe_dir} "
                     f"&& chmod -R a+rX {safe_dir}"),
                ],
                text=True,
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "ensure_claude_projects_readable failed: %s %s",
                    result.stdout, result.stderr,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("ensure_claude_projects_readable error: %s", e)

    # ── WSL copy helper ──────────────────────────────────────

    def wsl_copy_to_tmp(self, linux_src: str, linux_dst: str) -> bool:
        """Copy a file inside WSL as root, making it readable.

        When running inside WSL, uses direct ``cp`` (we are already root).
        When running on Windows, uses ``wsl.exe -u root -- cp``.

        Returns True on success.
        """
        try:
            if self.is_wsl:
                # Already inside WSL — direct copy
                import shutil
                shutil.copy2(linux_src, linux_dst)
                import os
                os.chmod(linux_dst, 0o644)
                return True

            # Windows: call wsl.exe to copy as root
            if not self.is_wsl_running():
                logger.debug(
                    "WSL distro '%s' not running, skipping copy of %s",
                    self.wsl_distro, linux_src,
                )
                return False
            safe_src = shlex.quote(linux_src)
            safe_dst = shlex.quote(linux_dst)
            result = _run_quiet(
                [
                    "wsl.exe", "-u", self.wsl_user_root, "-d", self.wsl_distro, "--",
                    "bash", "-c",
                    f"cp {safe_src} {safe_dst} && chmod 644 {safe_dst}",
                ],
                text=True,
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "wsl_copy_to_tmp failed: %s %s", result.stdout, result.stderr
                )
                return False
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, UnicodeDecodeError) as e:
            logger.warning("wsl_copy_to_tmp error: %s", e)
            return False


settings = Settings()
