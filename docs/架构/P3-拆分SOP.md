# P3 · Service 拆分 SOP（上下文体积治理）

> 目标：把 11 个超 500 行的 service 拆成「单文件 ≤ 500 行、单模块 ≤ 6000 行」，
> **业务行为零变化**，且拆分后 R4 从 warn 转 **CI fail**。

## 0. 为什么做（背景）

P1 目录重组把 39 个 service 下沉到 8 个模块，P2 把跨模块引用收口到 `contract.py`。
但 **R4（上下文体积）** 一直挂着：11 个文件 500~1400 行。

为什么在意这个：项目的目标是「让 AI agent 逐个开发、不互相踩」。
一个 1400 行的 service，agent 改它时要把 1400 行全读进上下文 —— 越大越容易
改错、越容易漏掉边界条件。**拆分的直接收益是让 agent 每次只读 300 行。**

拆分同时是**职责分离**：1400 行的 `delivery_service.py` 里混着「建单 / 状态流转 /
回传处理 / 查询」四件事，拆开后边界清晰，agent 才知道该改哪个文件。

## 1. 硬约束（违反即失败）

| 约束 | 说明 |
|---|---|
| **不改业务逻辑** | 只做物理重排。方法体逐字搬迁，SQL、状态机、错误码、幂等键一律不动 |
| **单文件 ≤ 500 行** | R4a |
| **单模块总行数 ≤ 6000** | R4b（比文件数更能约束真实目标） |
| **单模块文件数 ≤ 20** | R4c（P3 拆分必然增加文件数，由 12 放宽到 20） |
| **原 import 路径全部保持可用** | 源文件保留 re-export + `__all__` |
| **禁止新增模块内同名 public 符号** | 否则 `contract.py` 会退化成别名导出，调用方拿到错的实现 |
| **禁止循环 import** | 新文件不得反向 import 被它拆出来的源文件 |
| **不要跑 `tools/gen_module_public_api.py`** | 该工具由 P3 收尾统一执行（并行跑会互相覆盖 `contract.py`） |
| **不要跑 `tools/sync_contract_meta.py`** | 同上（收尾统一同步契约文档的「代码行 / service 个数」） |

## 2. 工具（已验证可用）

| 工具 | 作用 |
|---|---|
| `tools/split_service.py` | 按**顶层定义**（class / def / 大写常量）把一个文件切成多个文件；源文件变成 re-export |
| `tools/split_class.py` | 把一个**大 Service 类**按方法组拆成多个 `*Mixin` 文件；主类变成组合 |
| `tools/_split_common.py` | 自动补齐跨文件依赖（ruff F821 + **字符串类型注解**扫描） |

### 2.1 `split_service.py`

```bash
cd backend
.venv/bin/python ../tools/split_service.py app/modules/<mod>/service/<file>.py \
  --plan "<新文件>:<顶层名1>,<顶层名2>" \
  --plan "<源文件>:*" \                    # `*` = 留在源文件的其余定义
  --docstring "<新文件>=一句话职责说明"
```

行为：切块（**含装饰器行**）→ 新文件复制 import 区 → 源文件改写为 re-export +
`__all__` → ruff 清理 → 自动补跨文件 import。

### 2.2 `split_class.py`

```bash
.venv/bin/python ../tools/split_class.py app/modules/<mod>/service/<file>.py \
  --class <ClassName> \
  --mixin "<新文件>=<MixinClassName>:<方法1>,<方法2>" \
  --keep "__init__"
```

行为：把指派的方法原样搬进 `class <MixinClassName>:`；主类改为
`class <ClassName>(Mixin1, Mixin2):`，只保留 `--keep` 的成员；
自动从 `__init__` 推断实例属性类型并在 mixin 里声明。

## 3. 标准流程（每个文件 4 步）

### Step 1 —— 先切「常量 / 数据模型 / 小工具」层

大常量块（状态码、失败码、枚举、dataclass）与大 Service 类**必须分开**：
mixin 里的方法要用到这些常量，若常量留在源文件 → mixin 反向 import 源文件 → 循环 import。

```bash
.venv/bin/python ../tools/split_service.py <源文件> \
  --plan "<codes文件>:<常量1>,<常量2>,<Dataclass1>" \
  --plan "<源文件>:*"
```

### Step 2 —— 再切大类（按方法组 → mixin）

分组原则：**按业务职责分，不按行数均分**。每组 150~400 行。

```bash
.venv/bin/python ../tools/split_class.py <源文件> --class <ClassName> \
  --mixin "<a.py>=<AMixin>:<方法组A>" \
  --mixin "<b.py>=<BMixin>:<方法组B>" \
  --keep "__init__"
```

### Step 3 —— 人工核对跨文件依赖

工具会自动补 import，但要**人工确认三件事**：

1. `ruff check` 无 F821（未定义名）
2. `mypy` 无 `name-defined`（字符串注解里的类型）
3. **没有循环 import**：新文件不 import 源文件

### Step 4 —— 验证（三道关）

```bash
cd backend
.venv/bin/ruff check app --output-format=concise      # 必须 All checks passed
.venv/bin/python -m mypy app --ignore-missing-imports  # 必须 Success
.venv/bin/python -m pytest tests -q                     # 必须 411 passed（数字不得变）
```

## 4. 踩过的坑（别再踩）

| 坑 | 现象 | 处置 |
|---|---|---|
| **装饰器行被切丢** | `@dataclass` 丢失 → mypy 报 "Too many arguments" | 工具已修（切块含装饰器行） |
| **ruff 删掉 re-export** | 源文件的 `from x import Y` 被当未使用删掉 → 向后兼容路径全断 | 工具已修：源文件生成 `__all__`；私有名加 `# noqa: F401` |
| **模块级小写赋值被丢** | `logger = get_logger(__name__)` 消失 → NameError | 工具已修：保留所有未移走的顶层节点 |
| **循环 import** | 新文件 import 源文件 → ImportError | 常量层必须先切到独立文件；工具会检测并告警 |
| **mixin 的 attr-defined 误报** | mypy 报 `"Mixin" has no attribute "s"` | 工具已加 `# mypy: disable-error-code="attr-defined"` + 属性类型声明 |
| **模块文件数超限** | m4_fulfill 拆完 14 个文件 | R4c 上限由 12 放宽到 16，并新增 R4b 总行数 ≤ 6000 |
| **同名 public 符号** | contract.py 退化成 `X_stem` 别名 → 调用方拿到错的类 | 拆分时禁止在模块内新增同名符号；别名固化到 `tools/_contract_aliases.json`（符号换文件也**不改公开面名字**） |

## 5. 收尾（P3 收尾统一执行，拆分者不要做）

```bash
# 1. 重新生成契约公开面（会跳过 *Mixin，保持公开面干净；别名走稳定表 → 不改名）
backend/.venv/bin/python tools/gen_module_public_api.py

# 2. 同步契约文档的「代码行 / service 个数」（防两份契约不一致）
backend/.venv/bin/python tools/sync_contract_meta.py

# 3. R4 转 fail（与 R1/R2/R3 同级）
#    check_arch_rules.py --fail-on 默认值改为 R1,R2,R3,R4

# 4. 全量门禁
backend/.venv/bin/python tools/check_arch_rules.py
backend/.venv/bin/python -m pytest backend/tests -q
```

### 5.1 收尾必查的「公开面不变式」

拆分最容易出的错不是业务逻辑，而是**公开面被改名**（符号挪了文件 →
别名跟着变 → 跨模块调用方拿到错的东西）。收尾必须逐项 diff：

```bash
for m in m1_master m2_stock m3_trade m4_fulfill m5_abnormal m6_aftersale m7_integration m8_insight; do
  git show HEAD:backend/app/modules/$m/contract.py | backend/.venv/bin/python -c "
import sys,ast; t=ast.parse(sys.stdin.read())
print(sorted(n.value for x in t.body if isinstance(x,ast.Assign) and getattr(x.targets[0],'id','')=='__all__' for n in x.value.elts))"
  backend/.venv/bin/python -c "
import ast; t=ast.parse(open('backend/app/modules/$m/contract.py').read())
print(sorted(n.value for x in t.body if isinstance(x,ast.Assign) and getattr(x.targets[0],'id','')=='__all__' for n in x.value.elts))"
done
```

两行输出必须**逐项相同**。不同就说明公开面被改名了 → 查 `tools/_contract_aliases.json`。
