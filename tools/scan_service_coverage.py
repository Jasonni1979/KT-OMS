"""服务方法覆盖率扫描（整体检查第二轮 · 视角B）

按「服务类的公开方法是否被测试触及」盘点，找出**测试空白**的方法。
"""
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parents[1] / "backend"

svc_methods: dict[str, set[str]] = {}
for p in (BASE / "app/services").glob("*.py"):
    src = p.read_text(encoding="utf-8")
    for m in re.finditer(r"^class (\w+)", src, re.M):
        cls = m.group(1)
        body = src[m.end():]
        meths = set(re.findall(r"^\s+async def (\w+)\(", body, re.M))
        meths |= set(re.findall(r"^\s+def (\w+)\(", body, re.M))
        svc_methods.setdefault(cls, set()).update(meths)

test_text = ""
for pat in ("tests/test_*.py", "app/scripts/*_e2e.py"):
    for p in BASE.glob(pat):
        test_text += p.read_text(encoding="utf-8")

print(f"{'服务类':<26} {'方法':>5} {'被测':>5}  未测方法")
print("-" * 92)
total_m = 0
total_t = 0
gaps: list[tuple[str, list[str]]] = []
for cls in sorted(svc_methods):
    if not (cls.endswith("Service") or cls.endswith("Engine")):
        continue
    meths = {m for m in svc_methods[cls] if not m.startswith("_")}
    if not meths:
        continue
    # 判据：① 直接调用 `xxx.method(` ② 通过 API 路径间接覆盖
    #    （测试大量走 HTTP 接口 → 服务方法被间接调用，直接匹配会误报）
    covered = {m for m in meths if re.search(rf"[\w.]+\.{re.escape(m)}\(", test_text)}
    # API 层映射：端点里的动词 → 可能对应的服务方法名
    api_text = ""
    for ap in (BASE / "app/api/v1").glob("*.py"):
        api_text += ap.read_text(encoding="utf-8")
    for m in meths:
        if m in covered:
            continue
        # 该方法名在 API 层出现过（作为端点处理函数调用）→ 间接覆盖
        if re.search(rf"\b{re.escape(m)}\b", api_text):
            covered.add(m)
    unc = meths - covered
    total_m += len(meths)
    total_t += len(covered)
    if unc:
        gaps.append((cls, sorted(unc)))
    mark = "✓" if not unc else " "
    print(f"{mark}{cls:<25} {len(meths):>5} {len(covered):>5}  {', '.join(sorted(unc))[:46]}")

print("-" * 92)
pct = total_t / max(1, total_m) * 100
print(f"合计：公开方法 {total_m} 个，被触及 {total_t} 个（{pct:.0f}%）")
print()
print("=== 空白最多的类（优先补测）===")
for cls, unc in sorted(gaps, key=lambda x: -len(x[1]))[:8]:
    print(f"  {cls}（{len(unc)}）: {', '.join(unc)}")
