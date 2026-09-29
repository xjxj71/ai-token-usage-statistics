"""Tests for hidden console subprocess helpers."""

from __future__ import annotations

import subprocess
import sys

import pytest

from backend import config


@pytest.mark.unit
def test_no_window_flag_on_windows_only():
    if sys.platform == "win32":
        assert config._NO_WINDOW == {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        assert config._NO_WINDOW == {}


@pytest.mark.unit
def test_run_quiet_captures_output():
    result = config._run_quiet([sys.executable, "-c", "print('ok')"], timeout=10, text=True)
    assert result.returncode == 0
    assert "ok" in (result.stdout or "")
