import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import engine
from app.main import app


@pytest.fixture(autouse=True)
async def _dispose_engine():
    """每个测试后释放连接池：模块级 engine 跨 event loop 复用会残留连接，
    dispose 后下个测试在新 loop 重建连接（SQLAlchemy 官方推荐的测试隔离做法）。"""
    yield
    await engine.dispose()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client(client):
    """已登录 client（admin 超管，header 带 access token）——受保护业务域测试用"""
    r = await client.post("/api/v1/auth/login", json={
        "login_name": "admin", "password": "Ktoms@2026",
    })
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    yield client
    client.headers.pop("Authorization", None)

