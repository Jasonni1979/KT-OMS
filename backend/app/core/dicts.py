"""规则引擎框架 · 枚举字典服务（SRS-D01.03 FR-08）

**字典模型**（FR-08a）：
- 字典类型（`audit_reason_code`/`decision_code`/`suggest_action`…）→ 字典项
- 字典项：code/名称/描述/**级别**/扩展属性 JSON
  （审单原因码绑定**默认路由**与**审核组建议** → D03.02 FR-04b）

**服务能力**（FR-08b）：
- 注册（消费方代码启动时同步预置项）
- 查询（带缓存）
- 校验（规则配置与插件产出的 code 必须在字典内 —— 保存期 + 运行期双校验）
- **字典可扩展不发版**（后台增项即生效）

DB 落点：`oms_base.bas_rule_dict`（dict_category: dim/enum；dict_type: 字典类型名）。
代码里的常量是**权威定义**，DB 是登记副本（与导入模板同一策略：代码=权威，DB=登记）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseRuleDict


@dataclass
class DictItem:
    """字典项"""

    code: str
    name: str
    dict_type: str
    category: str = "enum"
    value_type: str = "string"
    level: str = ""
    description: str = ""
    ext: dict[str, Any] = field(default_factory=dict)
    sort_no: int = 0
    preset: bool = True

    @property
    def default_route(self) -> str:
        """默认路由（原因码 → 人工/缺货/复审/回池/挂起）"""
        return str(self.ext.get("default_route", "") or "")

    @property
    def audit_group(self) -> str:
        """建议审核组（原因码 → 审核组建议映射）"""
        return str(self.ext.get("audit_group", "") or "")

    @property
    def suggest_action(self) -> str:
        return str(self.ext.get("suggest_action", "") or "")


class DictService:
    """枚举字典服务（进程内缓存 + DB 登记副本）"""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, DictItem]] = {}

    # ---------- 预置定义（代码 = 权威） ----------

    def preset(self, dict_type: str) -> list[DictItem]:
        """返回预置字典项（消费方覆盖此方法或用 register_preset）"""
        return []

    def register_preset(self, dict_type: str, items: list[DictItem]) -> None:
        bucket = self._cache.setdefault(dict_type, {})
        for it in items:
            it.dict_type = dict_type
            bucket[it.code] = it

    # ---------- 查询 ----------

    def get(self, dict_type: str, code: str) -> DictItem | None:
        return self._cache.get(dict_type, {}).get(code)

    def list_items(self, dict_type: str) -> list[DictItem]:
        """列出字典项（FR-08b：查询带缓存）"""
        return sorted(
            self._cache.get(dict_type, {}).values(),
            key=lambda i: (i.sort_no, i.code),
        )

    def all_types(self) -> list[str]:
        return sorted(self._cache.keys())

    # ---------- 校验 ----------

    def exists(self, dict_type: str, code: str) -> bool:
        return code in self._cache.get(dict_type, {})

    def validate(self, dict_type: str, code: str) -> None:
        """运行期校验：code 必须在字典内（不存在即抛错）"""
        if not self.exists(dict_type, code):
            raise ValueError(f"字典项不存在: {dict_type}.{code}")

    # ---------- DB 同步（登记副本） ----------

    async def sync_to_db(self, session: AsyncSession, tenant_id: int = 1) -> int:
        """把内存中的预置字典登记到 DB（幂等 upsert）"""
        n = 0
        for dict_type, bucket in self._cache.items():
            for it in bucket.values():
                row = await session.scalar(
                    select(BaseRuleDict).where(
                        BaseRuleDict.dict_type == dict_type,
                        BaseRuleDict.item_code == it.code,
                        BaseRuleDict.is_deleted == 0,
                    )
                )
                payload = {
                    "tenant_id": tenant_id,
                    "dict_category": it.category,
                    "dict_type": dict_type,
                    "item_code": it.code,
                    "item_name": it.name,
                    "value_type": it.value_type,
                    "level": it.level,
                    "ext_json": json.dumps(it.ext, ensure_ascii=False) if it.ext else None,
                    "preset_flag": 1 if it.preset else 0,
                    "sort_no": it.sort_no,
                    "status": 1,
                }
                if row is None:
                    session.add(BaseRuleDict(**payload))
                else:
                    for k, v in payload.items():
                        if k != "tenant_id":
                            setattr(row, k, v)
                n += 1
        await session.commit()
        return n

    async def load_from_db(self, session: AsyncSession) -> int:
        """从 DB 加载自定义（后台增的）字典项到内存（可扩展不发版）"""
        rows = list(
            await session.scalars(
                select(BaseRuleDict).where(BaseRuleDict.status == 1, BaseRuleDict.is_deleted == 0)
            )
        )
        n = 0
        for row in rows:
            if row.dict_category != "enum":
                continue
            bucket = self._cache.setdefault(row.dict_type, {})
            ext: dict[str, Any] = {}
            if row.ext_json:
                try:
                    ext = json.loads(row.ext_json) if isinstance(row.ext_json, str) else row.ext_json
                except (TypeError, ValueError):
                    ext = {}
            item = DictItem(
                code=row.item_code,
                name=row.item_name,
                dict_type=row.dict_type,
                category=row.dict_category,
                value_type=row.value_type,
                level=row.level or "",
                ext=ext or {},
                sort_no=row.sort_no,
                preset=bool(row.preset_flag),
            )
            # 预置项以代码为准，DB 增补项直接入库
            if item.code not in bucket:
                bucket[item.code] = item
                n += 1
        return n


#: 全局字典服务单例
DICTS = DictService()
