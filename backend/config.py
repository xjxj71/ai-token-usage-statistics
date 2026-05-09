from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    wsl_distro: str = "project-claude"

    # WSL user whose home dir is accessible via UNC (claude = default WSL user)
    wsl_user_accessible: str = "claude"
    # WSL user whose files need root copy (hermes/openclaw run as root)
    wsl_user_root: str = "root"

    db_path: Path = Path("data/token_statistic.db")
    collector_state_path: Path = Path("data/collector_state.json")

    poll_interval_seconds: int = 5
    host: str = "127.0.0.1"
    port: int = 8001

    frontend_dist: Path = Path("frontend/dist")

    model_config = {"env_prefix": "TOKEN_STAT_"}

    @property
    def is_wsl(self) -> bool:
        """True if currently running inside WSL."""
        try:
            import platform
            return "microsoft" in platform.uname().release.lower()
        except Exception:
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
            result = subprocess.run(
                [
                    "wsl.exe", "-u", self.wsl_user_root, "-d", self.wsl_distro, "--",
                    "bash", "-c",
                    f"chown -R {self.wsl_user_accessible}:{self.wsl_user_accessible} '{linux_dir}' "
                    f"&& chmod -R a+rX '{linux_dir}'",
                ],
                capture_output=True,
                text=True,
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
            result = subprocess.run(
                [
                    "wsl.exe", "-u", self.wsl_user_root, "--",
                    "bash", "-c",
                    f"cp '{linux_src}' '{linux_dst}' && chmod 644 '{linux_dst}'",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "wsl_copy_to_tmp failed: %s %s", result.stdout, result.stderr
                )
                return False
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("wsl_copy_to_tmp error: %s", e)
            return False


settings = Settings()
