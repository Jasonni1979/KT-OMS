"""M2 商品与库存账本 —— **契约公开面（唯一对外接口）**

⚠ **跨模块 import 只能从本文件导入**（门禁 R2 强制）。
   `service/` 下的实现是内部细节，不对外承诺稳定性 ——
   需要跨模块用的能力，在此显式导出。

本文件由 `tools/gen_module_public_api.py` 生成，请勿手工编辑。
"""
from __future__ import annotations

from app.modules.m2_stock.service.freeze import (
    DEFAULT_TTL_HOURS,
    FreezeService,
)
from app.modules.m2_stock.service.import_center import (
    _ERROR_CODE_DESC,
    BATCH_SIZE,
    IMPORTER_REGISTRY,
    TEMPLATE_REGISTRY,
    UPLOAD_DIR,
    ImportContext,
    ImportService,
    get_importer,
    get_template,
    register_importer,
    register_template,
)
from app.modules.m2_stock.service.io_bill import (
    STATUS_CONFIRMED,
    STATUS_DRAFT,
    STATUS_FULL,
    STATUS_PARTIAL,
    STATUS_PUSHED,
    STATUS_RED_FLUSHED,
    TEMPLATE_FIELD_MAP,
    IoBillService,
)
from app.modules.m2_stock.service.material import (
    MaterialService,
    SalesMaterialService,
    crc32_of,
)
from app.modules.m2_stock.service.material_barcode import (
    BarcodeService,
)
from app.modules.m2_stock.service.material_bom import (
    BomExpandItem,
    BomService,
    bom_expand,
)
from app.modules.m2_stock.service.material_catalog import (
    _SPEC_NOISE,
    MAX_CAT_LEVEL,
    BrandService,
    CategoryService,
)
from app.modules.m2_stock.service.sellable import (
    CACHE_TTL,
    SellableResult,
    SellableService,
)
from app.modules.m2_stock.service.sku_mapping import (
    AUTOCREATE_LOCK_TTL,
    AUTOCREATE_TIMEOUT,
    LineMapping,
    SkuMappingService,
)
from app.modules.m2_stock.service.stock_ledger import (
    FIELD_MIN,
    LUA_DIR,
    REDIS_FIELD,
    StockLedgerService,
)
from app.modules.m2_stock.service.stock_recon import (
    FLOW_FIELD,
    RECON_FIELDS,
    ReconService,
)

__all__ = [
    "DEFAULT_TTL_HOURS",
    "FreezeService",
    "BATCH_SIZE",
    "IMPORTER_REGISTRY",
    "ImportContext",
    "ImportService",
    "TEMPLATE_REGISTRY",
    "UPLOAD_DIR",
    "_ERROR_CODE_DESC",
    "get_importer",
    "get_template",
    "register_importer",
    "register_template",
    "IoBillService",
    "STATUS_CONFIRMED",
    "STATUS_DRAFT",
    "STATUS_FULL",
    "STATUS_PARTIAL",
    "STATUS_PUSHED",
    "STATUS_RED_FLUSHED",
    "TEMPLATE_FIELD_MAP",
    "MaterialService",
    "SalesMaterialService",
    "crc32_of",
    "BarcodeService",
    "BomExpandItem",
    "BomService",
    "bom_expand",
    "BrandService",
    "CategoryService",
    "MAX_CAT_LEVEL",
    "_SPEC_NOISE",
    "CACHE_TTL",
    "SellableResult",
    "SellableService",
    "AUTOCREATE_LOCK_TTL",
    "AUTOCREATE_TIMEOUT",
    "LineMapping",
    "SkuMappingService",
    "FIELD_MIN",
    "LUA_DIR",
    "REDIS_FIELD",
    "StockLedgerService",
    "FLOW_FIELD",
    "RECON_FIELDS",
    "ReconService",
]
