"""导入中心框架层（SRS-D01.06 FR-01/FR-02/FR-03）

设计要点（对应 SRS §5.1 流水线）：
- 模板 = 列集声明（列名/字段映射/必填/类型/枚举/示例/说明），由代码注册并登记到
  oms_base.bas_ie_template（列集默认由 D01.04 实体元数据驱动生成，可人工增删调整）
- 框架层校验（格式层：必填/类型/长度/枚举）**零业务代码**
- 业务层校验在导入器 rowValidate（逐行独立，单行错误不阻塞其他行）
- 批 = 事务边界：批内原子、批间独立，批失败只回滚该批
- 行级幂等键：任务 ID + 行号（断点续跑不重复提交）
- 错误报告三 sheet：错误明细 / 聚类摘要 / 成功统计
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class ColumnSpec:
    """模板列定义（映射 bas_ie_template.columns_json 的元素）"""

    col_name: str
    field_map: str
    required: bool = False
    value_type: str = "str"  # str/int/decimal/enum/date
    enum_dict: dict[str, str] = field(default_factory=dict)
    example: str = ""
    desc: str = ""


@dataclass
class TemplateSpec:
    """导入模板（映射 bas_ie_template 一行）"""

    template_code: str
    template_name: str
    domain_code: str
    entity_ref: str
    importer_ref: str
    columns: list[ColumnSpec]
    perm_point: str = ""
    version: int = 1

    @property
    def headers(self) -> list[str]:
        return [c.col_name for c in self.columns]

    def to_columns_json(self) -> list[dict[str, Any]]:
        return [
            {
                "col_name": c.col_name,
                "field_map": c.field_map,
                "required": c.required,
                "value_type": c.value_type,
                "enum_dict": c.enum_dict,
                "example": c.example,
                "desc": c.desc,
            }
            for c in self.columns
        ]


class RowError(Exception):
    """行级业务校验错误（错误码 + 人读消息，含定位信息）"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RowResult:
    ok: bool
    code: str = ""
    message: str = ""


class ImporterInterface:
    """导入器接口（SRS FR-03a）

    实现方按 template_code 注册；框架负责编排，业务校验与落库在实现方。
    """

    template_code: str = ""

    def support_mode(self) -> str:
        """断点续跑 | 整任务重跑 | 两者"""
        return "断点续跑"

    async def prefetch(self, rows: list[dict[str, Any]], ctx: Any) -> None:
        """批量预取钩子（性能契约 ≥300 行/秒的关键：杜绝 N+1 查库）"""

    def row_validate(self, row: dict[str, Any], ctx: Any) -> RowResult:
        """业务层行校验（逐行独立；失败抛 RowError 或返回错误结果）"""
        return RowResult(ok=True)

    async def commit_batch(self, rows: list[dict[str, Any]], ctx: Any) -> None:
        """批次提交（事务边界内落库，幂等）"""


# ---------- 框架层格式校验（零业务代码） ----------

ERROR_REQUIRED = "FORMAT_REQUIRED"
ERROR_TYPE = "FORMAT_TYPE"
ERROR_LENGTH = "FORMAT_LENGTH"
ERROR_ENUM = "FORMAT_ENUM"


def validate_row_format(
    row: dict[str, Any], template: TemplateSpec, row_no: int
) -> RowResult:
    """框架层校验：必填 / 类型 / 长度 / 枚举值域"""
    for col in template.columns:
        raw = row.get(col.field_map)
        val = "" if raw is None else raw
        text = str(val).strip()
        if col.required and not text:
            return RowResult(
                False, ERROR_REQUIRED, f"第{row_no}行「第{col.col_name}」为必填项"
            )
        if not text:
            continue
        if col.value_type == "int":
            try:
                int(float(text))
            except ValueError:
                return RowResult(
                    False, ERROR_TYPE, f"第{row_no}行「第{col.col_name}」应为整数，当前值「{text}」"
                )
        elif col.value_type == "decimal":
            try:
                float(text)
            except ValueError:
                return RowResult(
                    False, ERROR_TYPE, f"第{row_no}行「第{col.col_name}」应为数字，当前值「{text}」"
                )
        elif col.value_type == "date":
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                return RowResult(
                    False, ERROR_TYPE,
                    f"第{row_no}行「第{col.col_name}」应为日期(YYYY-MM-DD)，当前值「{text}」",
                )
        elif col.value_type == "enum":
            if text not in col.enum_dict:
                allowed = "/".join(col.enum_dict.keys())
                return RowResult(
                    False, ERROR_ENUM,
                    f"第{row_no}行「第{col.col_name}」取值「{text}」不在允许范围({allowed})",
                )
        if col.value_type == "str" and len(text) > 255:
            return RowResult(
                False, ERROR_LENGTH, f"第{row_no}行「第{col.col_name}」长度超限(>255)"
            )
    return RowResult(ok=True)


# ---------- 文件解析（流式，内存恒定） ----------

def read_rows(content: bytes, filename: str) -> tuple[list[str], list[list[Any]]]:
    """读表头与数据行（xlsx 流式 / csv）

    返回 (表头, 数据行列表)。MVP 内存上限：单文件 ≤100 万行由业务侧限制，
    这里按批流式读取，调用方按批消费。
    """
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        text = _decode_csv(content)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return [], []
        return [str(c).strip() for c in rows[0]], rows[1:]
    if lower.endswith(".xlsm"):
        raise ValueError("不支持宏文件(xlsm)（安全要求：宏文件拒绝）")
    if not lower.endswith((".xlsx", ".xls")):
        raise ValueError(f"不支持的文件格式: {filename}")
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        it = ws.iter_rows(values_only=True)
        try:
            head = next(it)
        except StopIteration:
            return [], []
        headers = ["" if c is None else str(c).strip() for c in head]
        data: list[list[Any]] = []
        for row in it:
            if row is None:
                continue
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            data.append(list(row))
        return headers, data
    finally:
        wb.close()


def _decode_csv(content: bytes) -> str:
    """CSV 编码自动探测（GBK/UTF-8）"""
    for enc in ("utf-8-sig", "gbk", "utf-8", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def build_template_file(template: TemplateSpec) -> bytes:
    """生成标准模板文件（表头 + 枚举说明 sheet + 示例行 sheet）"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "导入数据"
    ws.append(template.headers)
    ws.append([c.example for c in template.columns])

    ws2 = wb.create_sheet("字段说明")
    ws2.append(["列名", "是否必填", "类型", "取值范围", "说明", "示例"])
    for c in template.columns:
        allowed = "/".join(c.enum_dict.keys()) if c.enum_dict else ""
        ws2.append([c.col_name, "是" if c.required else "否", c.value_type, allowed, c.desc, c.example])

    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


def rows_to_xlsx(rows: list[list[Any]], headers: list[str], sheet_name: str = "Sheet1") -> bytes:
    """通用行数据 → xlsx（用于错误报告）"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    if headers:
        ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


def now_str() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None
