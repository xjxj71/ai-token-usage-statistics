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
    port: int = 8000

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
