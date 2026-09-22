"""Tests for backend.paths layout resolution."""

from __future__ import annotations

import pytest

from backend import paths


@pytest.mark.unit
class TestLayout:
    def test_dev_mode_uses_repo_root(self, monkeypatch, tmp_path):
        monkeypatch.delattr(paths.sys, "frozen", raising=False)
        monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
        monkeypatch.setattr(paths, "is_frozen", lambda: False)
        monkeypatch.setattr(paths, "portable_mode", lambda: False)

        assert paths.data_dir() == tmp_path / "data"
        assert paths.config_dir() == tmp_path / "config"
        assert paths.db_path() == tmp_path / "data" / "token_statistic.db"
        assert paths.instance_state_path() == tmp_path / "data" / "instance.json"
        assert paths.quota_providers_path() == tmp_path / "config" / "quota_providers.yaml"

    def test_frozen_install_uses_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "portable_mode", lambda: False)

        data = paths.data_dir()
        cfg = paths.config_dir()
        assert data == tmp_path / "Roaming" / "ai-token-usage" / "data"
        assert cfg == tmp_path / "Roaming" / "ai-token-usage" / "config"
        assert paths.backups_dir() == data / "backups"
        assert paths.app_log_path() == data / "app.log"

    def test_frozen_portable_uses_app_root(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "portable_mode", lambda: True)
        monkeypatch.setattr(paths, "app_root", lambda: tmp_path)

        assert paths.data_dir() == tmp_path / "data"
        assert paths.config_dir() == tmp_path / "config"

    def test_temp_dir_prefers_temp_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEMP", str(tmp_path / "Tmp"))
        assert paths.temp_dir() == tmp_path / "Tmp"

    def test_collector_temp_prefix_lands_in_temp(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEMP", str(tmp_path / "Tmp"))
        p = paths.collector_temp_prefix("hermes")
        assert p == tmp_path / "Tmp" / "ai-token-usage-hermes"


@pytest.mark.unit
class TestInitUserDirs:
    def test_creates_dirs_and_seeds_template(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_frozen", lambda: False)
        monkeypatch.setattr(paths, "portable_mode", lambda: False)
        monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
        monkeypatch.setattr(paths, "bundle_root", lambda: tmp_path)

        example = tmp_path / "config" / "quota_providers.example.yaml"
        example.parent.mkdir(parents=True)
        example.write_text("providers: {}\n", encoding="utf-8")

        paths.init_user_dirs()

        assert paths.data_dir().is_dir()
        assert paths.backups_dir().is_dir()
        assert paths.config_dir().is_dir()
        assert paths.quota_providers_path().read_text(encoding="utf-8") == "providers: {}\n"

    def test_does_not_overwrite_existing_config(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_frozen", lambda: False)
        monkeypatch.setattr(paths, "portable_mode", lambda: False)
        monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
        monkeypatch.setattr(paths, "bundle_root", lambda: tmp_path)

        example = tmp_path / "config" / "quota_providers.example.yaml"
        example.parent.mkdir(parents=True)
        example.write_text("providers: {}\n", encoding="utf-8")

        dest = tmp_path / "config" / "quota_providers.yaml"
        dest.write_text("providers:\n  zhipu:\n    enabled: true\n", encoding="utf-8")

        paths.init_user_dirs()
        assert "zhipu" in dest.read_text(encoding="utf-8")
