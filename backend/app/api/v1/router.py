"""API v1 路由聚合（模块化单体：每域一个 router，按 SRS 域编号组织）"""
from fastapi import APIRouter, Depends

from app.api.v1 import (
    abnormal,
    abnormal_ext,
    aftersale,
    audit,
    auth,
    fulfill,
    hello,
    import_center,
    master,
    material,
    modify,
    monitor,
    order,
    stock,
    wms,
)
from app.core.deps import get_current_account

api_router = APIRouter()
api_router.include_router(hello.router, prefix="/hello")
api_router.include_router(auth.router, prefix="/auth")  # D10.02 认证
# 档案域起全部业务路由默认需登录（dependencies 在 include 层统一挂）
api_router.include_router(
    master.router, prefix="/master",
    dependencies=[Depends(get_current_account)],
)  # D10.01 档案域
api_router.include_router(
    material.router, prefix="/material",
    dependencies=[Depends(get_current_account)],
)  # D04.01 物料域
api_router.include_router(
    import_center.router, prefix="/import",
    dependencies=[Depends(get_current_account)],
)  # D01.06 导入中心
api_router.include_router(
    stock.router, prefix="/stock",
    dependencies=[Depends(get_current_account)],
)  # D04.02 库存记账
api_router.include_router(
    order.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D02 拉单 + D03 订单接入
api_router.include_router(
    audit.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D03.02 审单引擎 + D03.03 人工审单工作台
api_router.include_router(
    fulfill.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D03.06 分仓 + D03.04 拆单 + D03.07 发货单（W6 履约域）
api_router.include_router(
    wms.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D09.01 路由 + D09.02 出库指令通道（W7 履约通道）
api_router.include_router(
    abnormal.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D03.09 异常单与缺货处理（W8）
api_router.include_router(
    monitor.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D11.03 履约监控看板（W8-3）
api_router.include_router(
    modify.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D03.08 订单修改与改地址（W8-3）
api_router.include_router(
    aftersale.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D05 售后服务（W9-1）
api_router.include_router(
    abnormal_ext.router, prefix="",
    dependencies=[Depends(get_current_account)],
)  # D03.09 应急批次/暂停编排/名单服务（W9-2）

# M1 起按域挂载：
# api_router.include_router(org.router, prefix="/org")        # D10
# api_router.include_router(material.router, prefix="/materials")  # D04.01
# api_router.include_router(stock.router, prefix="/stock")    # D04
# api_router.include_router(order.router, prefix="/orders")   # D03
# api_router.include_router(gateway.router, prefix="/gateway")  # D02
