"""API v1 路由聚合（模块化单体：每域一个 router，按 SRS 域编号组织）"""
from fastapi import APIRouter

from app.api.v1 import hello, master

api_router = APIRouter()
api_router.include_router(hello.router, prefix="/hello")
api_router.include_router(master.router, prefix="/master")  # D10.01 档案域

# M1 起按域挂载：
# api_router.include_router(org.router, prefix="/org")        # D10
# api_router.include_router(material.router, prefix="/materials")  # D04.01
# api_router.include_router(stock.router, prefix="/stock")    # D04
# api_router.include_router(order.router, prefix="/orders")   # D03
# api_router.include_router(gateway.router, prefix="/gateway")  # D02
