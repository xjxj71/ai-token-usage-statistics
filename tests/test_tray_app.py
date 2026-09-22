"""Unit tests for tray helpers that do not require a GUI."""

from __future__ import annotations

import socket

import pytest

from backend import paths, tray_app


@pytest.mark.unit
def test_find_free_port_skips_busy():
    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    port = busy.getsockname()[1]
    try:
        found = tray_app.find_free_port(port, host="127.0.0.1", attempts=5)
        assert found != port
        assert found > port
    finally:
        busy.close()


@pytest.mark.unit
def test_instance_state_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.setattr(paths, "portable_mode", lambda: False)
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")

    state = tray_app.write_instance_state("127.0.0.1", 8002)
    assert state["base_url"] == "http://127.0.0.1:8002"
    loaded = tray_app.read_instance_state()
    assert loaded is not None
    assert loaded["port"] == 8002

    tray_app.clear_instance_state()
    assert tray_app.read_instance_state() is None


@pytest.mark.unit
def test_read_instance_state_tolerates_garbage(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "instance.json").write_text("{not json", encoding="utf-8")
    assert tray_app.read_instance_state() is None


@pytest.mark.unit
def test_resolve_existing_base_url_default():
    assert tray_app.resolve_existing_base_url() == "http://127.0.0.1:8001"
