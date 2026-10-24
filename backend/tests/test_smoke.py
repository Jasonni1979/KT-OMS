"""M0 骨架冒烟测试：健康检查 + 统一响应 + 跨 schema 查询 + 异常处理"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_healthz(client):
    r = await client.get("/api/v1/hello/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0 and body["data"]["status"] == "up"
    assert "x-trace-id" in r.headers   # TraceMiddleware 生效


async def test_readyz_db(client):
    r = await client.get("/api/v1/hello/readyz")
    assert r.status_code == 200
    assert r.json()["data"]["db"] == "up"


async def test_tenants_cross_schema(client):
    r = await client.get("/api/v1/hello/tenants")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "total" in data and "items" in data


async def test_404_envelope(client):
    r = await client.get("/api/v1/nonexistent")
    assert r.status_code == 404
    assert r.json()["code"] == "HTTP_404"
