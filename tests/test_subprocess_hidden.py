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


@pytest.mark.unit
def test_wsl_running_ttl_asymmetric(monkeypatch):
    """A 'stopped' answer is trusted longer than a 'running' one.

    Each wsl.exe spawn costs seconds; the old fixed 2s TTL paid that twice
    per poll cycle (claude_code + hermes guards) even though there is
    nothing to collect while the distro is stopped.
    """
    s = config.settings
    calls: list[int] = []
    monkeypatch.setattr(s, "_wsl_running_cache", None)
    monkeypatch.setattr(s, "_query_wsl_running", lambda: calls.append(1) or False)

    assert s.is_wsl_running() is False
    assert s.is_wsl_running() is False
    assert len(calls) == 1  # fresh answer is cached, no second spawn

    t0 = s._wsl_running_cache[0]
    s._wsl_running_cache = (t0 - 5, False)  # 5s old: inside the stopped TTL
    assert s.is_wsl_running() is False
    assert len(calls) == 1

    s._wsl_running_cache = (t0 - 16, False)  # past the stopped TTL: re-query
    assert s.is_wsl_running() is False
    assert len(calls) == 2

    monkeypatch.setattr(s, "_query_wsl_running", lambda: calls.append(1) or True)
    s._wsl_running_cache = (t0 - 16, True)
    assert s.is_wsl_running() is True
    assert len(calls) == 3

    s._wsl_running_cache = (t0 - 3, True)  # past the running TTL (2s)
    assert s.is_wsl_running() is True
    assert len(calls) == 4
