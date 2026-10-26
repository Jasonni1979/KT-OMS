"""E2E 断言收集器（公共）

W8 复盘发现：各 E2E 脚本各写一份 `Checker` 类（重复代码），且**断言条数没有
下限校验**时容易「静默不跑」。本模块统一提供：

- `Checker`：断言收集 + 渲染
- `assert_min` 语义内置在 `render_summary()` —— 汇总时输出断言总数，
  供 `deploy/ci-local-rehearsal.sh` 的 `assert_min()` 校验下限
"""
from __future__ import annotations


class Checker:
    """断言收集器（E2E 通用）"""

    def __init__(self, title: str = "") -> None:
        self.title = title
        self.passed = 0
        self.failed = 0
        self.lines: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        """记录一条断言"""
        if cond:
            self.passed += 1
            self.lines.append(f"  [PASS] {name}" + (f" | {detail}" if detail else ""))
        else:
            self.failed += 1
            self.lines.append(f"  [FAIL] {name}" + (f" | {detail}" if detail else ""))
        return cond

    def section(self, title: str) -> None:
        """插入一段小标题（不计入断言数）"""
        self.lines.append(f"--- {title} ---")

    @property
    def total(self) -> int:
        return self.passed + self.failed

    def render(self) -> str:
        if self.title:
            head = f"===== {self.title} ====="
        else:
            head = ""
        body = "\n".join(self.lines)
        return f"{head}\n{body}" if head else body

    def summary(self) -> str:
        """汇总行（CI 脚本用 `合计：N/M 项通过` 提取）"""
        return f"合计：{self.passed}/{self.total} 项通过"

    def exit_code(self) -> int:
        return 0 if self.failed == 0 else 1

    def print_all(self) -> None:
        print(self.render())
        print(f"\n{self.summary()}")
