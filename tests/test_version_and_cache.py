"""版本号单一来源与前端缓存策略测试。"""

import tomllib

import pytest

from backend import paths
from backend.version import get_app_version


@pytest.mark.unit
def test_app_version_matches_pyproject():
    with open(paths.app_root() / "pyproject.toml", "rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    assert get_app_version() == expected


@pytest.mark.integration
@pytest.mark.asyncio
async def test_index_html_no_cache(client):
    """index.html 协商缓存：应用更新后普通刷新即可拿到新前端。"""
    if not paths.frontend_dist().exists():
        pytest.skip("frontend dist not built")
    res = await client.get("/")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hashed_assets_immutable(client):
    """带哈希的构建产物长期缓存。"""
    assets = paths.frontend_dist() / "assets"
    if not assets.is_dir():
        pytest.skip("frontend dist not built")
    js = next(assets.glob("*.js"), None)
    if js is None:
        pytest.skip("no js asset")
    res = await client.get(f"/assets/{js.name}")
    assert res.status_code == 200
    assert "immutable" in res.headers["cache-control"]