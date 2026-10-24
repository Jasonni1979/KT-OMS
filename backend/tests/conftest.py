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

