import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.db import database as db_module
from backend.db.models import TokenRecord, insert_records
from backend.main import app


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    from backend import config

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config.settings, "db_path", db_path)

    await db_module.close_db()

    await db_module.init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await db_module.close_db()


@pytest.mark.asyncio
async def test_summary_empty(client):
    res = await client.get("/api/summary?range=custom&from=2026-01-01&to=2027-01-01")
    assert res.status_code == 200
    data = res.json()
    assert data["total_tokens"] == 0
    assert data["call_count"] == 0


@pytest.mark.asyncio
async def test_summary_with_data(client):
    db = await db_module.get_db()
    records = [
        TokenRecord(
            timestamp="2026-05-02T10:00:00Z",
            agent="claude-code",
            model="claude-sonnet-4-6",
            session_id="s1",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cost_usd=0.005,
        ),
        TokenRecord(
            timestamp="2026-05-02T11:00:00Z",
            agent="hermes",
            model="gpt-4o",
            session_id="s2",
            input_tokens=2000,
            output_tokens=1000,
            cost_usd=0.01,
        ),
    ]
    await insert_records(db, records)

    res = await client.get("/api/summary?range=custom&from=2026-01-01&to=2027-01-01")
    assert res.status_code == 200
    data = res.json()
    assert data["input_tokens"] == 3000
    assert data["output_tokens"] == 1500
    assert data["call_count"] == 2
    assert len(data["breakdown"]) == 2


@pytest.mark.asyncio
async def test_usage_pagination(client):
    db = await db_module.get_db()
    records = [
        TokenRecord(
            timestamp="2026-05-02T10:00:00Z",
            agent="claude-code",
            model="claude-sonnet-4-6",
            input_tokens=i * 100,
            output_tokens=i * 50,
        )
        for i in range(5)
    ]
    await insert_records(db, records)

    res = await client.get("/api/usage?page=1&limit=3&from=2026-01-01&to=2027-01-01")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert len(data["items"]) == 3
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_agents_endpoint(client):
    db = await db_module.get_db()
    records = [
        TokenRecord(timestamp="2026-05-02T10:00:00Z", agent="claude-code", model="m1"),
        TokenRecord(timestamp="2026-05-02T10:00:00Z", agent="hermes", model="m2"),
    ]
    await insert_records(db, records)

    res = await client.get("/api/agents")
    assert res.status_code == 200
    data = res.json()
    assert "claude-code" in data
    assert "hermes" in data


@pytest.mark.asyncio
async def test_pricing_endpoint(client):
    res = await client.get("/api/pricing")
    assert res.status_code == 200
    data = res.json()
    assert len(data) > 0
    assert any(p["model"] == "claude-sonnet-4-6" for p in data)


@pytest.mark.asyncio
async def test_filter_by_agent(client):
    db = await db_module.get_db()
    records = [
        TokenRecord(timestamp="2026-05-02T10:00:00Z", agent="claude-code", model="m1", input_tokens=100),
        TokenRecord(timestamp="2026-05-02T10:00:00Z", agent="hermes", model="m2", input_tokens=200),
    ]
    await insert_records(db, records)

    res = await client.get("/api/summary?range=custom&from=2026-01-01&to=2027-01-01&agent=claude-code")
    assert res.status_code == 200
    data = res.json()
    assert data["input_tokens"] == 100
    assert data["call_count"] == 1
