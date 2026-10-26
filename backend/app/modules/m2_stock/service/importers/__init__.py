"""导入器集合（导入即注册模板与导入器，SRS-D01.06 FR-03a）"""
from app.modules.m2_stock.service.importers.initial_stock_importer import (
    INITIAL_TEMPLATE,
    InitialStockImporter,
)
from app.modules.m2_stock.service.importers.material_importer import MATERIAL_TEMPLATE, MaterialImporter

__all__ = [
    "INITIAL_TEMPLATE",
    "MATERIAL_TEMPLATE",
    "InitialStockImporter",
    "MaterialImporter",
]
