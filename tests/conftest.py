"""Shared test fixtures for the ai-token-usage-statistics project."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.db import database as db_module
from backend.main import app


@pytest.fixture(autouse=True)
def _isolated_multiplier_cache(tmp_path, monkeypatch):
    """Keep multiplier tests hermetic: reset registry state and keep any
    persistence inside tmp_path (never the repo's data/ directory)."""
    from backend.quota import multipliers as mult_module

    monkeypatch.setattr(
        mult_module, "_persist_path", lambda: tmp_path / "model_multipliers.json"
    )
    mult_module._reset_for_tests()
    yield
    mult_module._reset_for_tests()


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Provide an HTTP client with a fresh temporary database."""
    from backend import config

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config.settings, "db_path", db_path)

    await db_module.close_db()
    await db_module.init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await db_module.close_db()
