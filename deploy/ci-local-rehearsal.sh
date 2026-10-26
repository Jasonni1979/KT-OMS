#!/usr/bin/env bash
# CI 本地全量复演（与 .github/workflows/ci.yml 四个 job 逐步骤等价）
# 用途：推送前自检，避免再收到失败邮件
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }


# ============ 断言条数下限校验（复盘新增）============
# 复盘实测：E2E 的断言可能因数据前置条件不满足而「静默不跑」——
# 门禁显示通过，实际少了覆盖（W7 通道 E2E 开发库 23 条 / CI 库 21 条）。
# 因此每个 E2E 门禁都要校验断言条数下限。
assert_min() {
  local log="$1" min="$2" label="$3"
  local got
  got=$(grep -oE '\[PASS\]' "$log" | wc -l | tr -d ' ')
  if [ "$got" -ge "$min" ]; then
    ok "$label 断言数 $got ≥ $min"
  else
    bad "$label 断言数 $got < $min（有断言被静默跳过）"
    tail -15 "$log"
  fi
}

echo "=== Job 1/4: Backend (ruff + mypy) ==="
(cd "$ROOT/backend" && "$PY" -m ruff check app tests --output-format=concise >/tmp/ci_ruff.log 2>&1) \
  && ok "ruff" || { bad "ruff"; tail -5 /tmp/ci_ruff.log; }
(cd "$ROOT/backend" && "$PY" -m mypy app --ignore-missing-imports >/tmp/ci_mypy.log 2>&1) \
  && ok "mypy" || { bad "mypy"; tail -5 /tmp/ci_mypy.log; }

echo "=== Job 2/4: Backend (pytest + MySQL/Redis) ==="
# 用独立 CI 库（自动选空闲端口），避免污染开发库 3308
docker rm -f ci_ci_mysql ci_test_mysql >/dev/null 2>&1
CI_PORT=13306
for p in 13306 13307 13308 13309; do
  if ! lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1 && ! docker ps --format "{{.Ports}}" | grep -q ":$p->"; then
    CI_PORT=$p; break
  fi
done
echo "  (CI 复演库端口: $CI_PORT)"
docker run -d --name ci_ci_mysql -e MYSQL_ROOT_PASSWORD=ktoms_dev_2026 -p ${CI_PORT}:3306 \
  docker.1ms.run/mysql:8.0 --character-set-server=utf8mb4 --collation-server=utf8mb4_0900_ai_ci >/dev/null
# 就绪探测必须走 TCP：MySQL 初始化期服务以 --skip-networking 启动（仅 socket 可用），
# 此时 mysqladmin ping 会成功但 TCP 3306 尚未监听 → 需 SELECT 1 走 TCP 确认真正就绪
for i in $(seq 1 60); do
  if docker exec ci_ci_mysql mysql -h 127.0.0.1 -uroot -pktoms_dev_2026 -N -e "SELECT 1" >/dev/null 2>&1; then
    echo "  (MySQL 就绪，第${i}次探测)"; break
  fi
  sleep 3
done
DDL_OK=1
for f in "$ROOT"/docs/database/sql/*.sql; do
  docker exec -i ci_ci_mysql mysql -h 127.0.0.1 -uroot -pktoms_dev_2026 < "$f" >/tmp/ci_ddl.log 2>&1 \
    || { bad "DDL $(basename "$f")"; head -3 /tmp/ci_ddl.log; DDL_OK=0; }
done
[ "$DDL_OK" = "1" ] && ok "DDL 导入（11 份）"
TABLES=$(docker exec ci_ci_mysql mysql -h 127.0.0.1 -uroot -pktoms_dev_2026 -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema LIKE 'oms_%';" 2>/dev/null | tr -d '\r')
if [ "$TABLES" = "373" ]; then ok "表数 373"; else bad "表数 ${TABLES:-0}（预期 373）"; fi

CI_REDIS_PORT=16379
docker rm -f ci_ci_redis >/dev/null 2>&1
docker run -d --name ci_ci_redis -p ${CI_REDIS_PORT}:6379 docker.1ms.run/redis:7-alpine >/dev/null
for i in $(seq 1 30); do
  docker exec ci_ci_redis redis-cli ping 2>/dev/null | grep -q PONG && break
  sleep 2
done
export KTOMS_MYSQL_HOST=127.0.0.1 KTOMS_MYSQL_PORT=$CI_PORT KTOMS_REDIS_URL="redis://127.0.0.1:$CI_REDIS_PORT/0"
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_org >/tmp/ci_seed1.log 2>&1) \
  && ok "seed_org" || { bad "seed_org"; tail -5 /tmp/ci_seed1.log; }
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_auth >/tmp/ci_seed2.log 2>&1) \
  && ok "seed_auth" || { bad "seed_auth"; tail -5 /tmp/ci_seed2.log; }
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_import >/tmp/ci_seed3.log 2>&1) \
  && ok "seed_import" || { bad "seed_import"; tail -5 /tmp/ci_seed3.log; }
# W5：审单域种子（原因码字典 + 审单规则 + 审核组 + 分派规则 + 仓物流绑定）
# 缺它 → 审单链无候选仓/物流 → 场景与审单用例路径与开发库不一致
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_audit >/tmp/ci_seed4.log 2>&1) \
  && ok "seed_audit" || { bad "seed_audit"; tail -8 /tmp/ci_seed4.log; }
# W6：履约域种子（分仓规则 + 拆单规则）
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_fulfill >/tmp/ci_seed5.log 2>&1) \
  && ok "seed_fulfill" || { bad "seed_fulfill"; tail -8 /tmp/ci_seed5.log; }
# W7：WMS 档案 + 仓×WMS 绑定（推仓通道路由需要）
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_wms >/tmp/ci_seed6.log 2>&1) \
  && ok "seed_wms" || { bad "seed_wms"; tail -8 /tmp/ci_seed6.log; }
(cd "$ROOT/backend" && "$PY" -m pytest tests/ -q >/tmp/ci_pytest.log 2>&1) \
  && ok "pytest（$(grep -oE '[0-9]+ passed' /tmp/ci_pytest.log | tail -1)）" \
  || { bad "pytest"; tail -20 /tmp/ci_pytest.log; }

echo "=== Job 2b: 模型 ↔ DDL 列一致性（W5/W6 连续三轮踩过 DDL 列名坑）==="
# 逐表逐列比对 ORM 声明与 information_schema → 不一致即失败
(cd "$ROOT/backend" && "$PY" ../tools/check_model_ddl.py >/tmp/ci_modelddl.log 2>&1) \
  && ok "模型 ↔ DDL 一致性" || { bad "模型 ↔ DDL 不一致"; tail -15 /tmp/ci_modelddl.log; }

echo "=== Job 3/4: Mock Platform (pytest) ==="
(cd "$ROOT/mocks/platform" && "$PY" -m pytest tests/ -q >/tmp/ci_mock.log 2>&1) \
  && ok "mock pytest（$(grep -oE '[0-9]+ passed' /tmp/ci_mock.log | tail -1)）" \
  || { bad "mock pytest"; tail -15 /tmp/ci_mock.log; }

echo "=== Job 3b/4: Mock WMS (pytest) ==="
# W7 新增：WMS 模拟器契约测试（指令下发/叫回/状态回放/回传幂等/错误注入）
(cd "$ROOT/mocks/wms" && "$PY" -m pytest tests/ -q >/tmp/ci_mockwms.log 2>&1) \
  && ok "mock-wms pytest（$(grep -oE '[0-9]+ passed' /tmp/ci_mockwms.log | tail -1)）" \
  || { bad "mock-wms pytest"; tail -15 /tmp/ci_mockwms.log; }

echo "=== Job 5/5: 测试用例清单与代码同步（交付文档防脱节）==="
(cd "$ROOT" && "$PY" tools/gen_test_doc.py --check >/tmp/ci_testdoc.log 2>&1) \
  && ok "测试用例清单与代码同步" || { bad "测试用例清单与代码不同步"; tail -20 /tmp/ci_testdoc.log; }

echo "=== Job 6/6: 业务场景端到端（跨域契约衔接门禁）==="
# 场景自起模拟器 → 主数据→期初→下单→拉单→预占→出库→记账 全链路断言
(cd "$ROOT/backend" && "$PY" -m app.scripts.scenario_e2e --with-mock >/tmp/ci_scenario.log 2>&1) \
  && ok "业务场景端到端（$(grep -oE '合计：[0-9]+/[0-9]+ 项通过' /tmp/ci_scenario.log | tail -1)）" \
  || { bad "业务场景端到端"; tail -25 /tmp/ci_scenario.log; }
assert_min /tmp/ci_scenario.log 14 "业务场景端到端"

echo "=== Job 7/7: 履约链路端到端（W6：分仓→拆单→发货单状态机）==="
# 43 项断言：整仓分配/多仓兜底/缺货分级/按货主拆/守恒校验/状态机全链路/回传幂等/差异登记
(cd "$ROOT/backend" && "$PY" -m app.scripts.fulfill_e2e >/tmp/ci_fulfill.log 2>&1) \
  && ok "履约链路端到端（$(grep -oE '合计：[0-9]+/[0-9]+ 项通过' /tmp/ci_fulfill.log | tail -1)）" \
  || { bad "履约链路端到端"; tail -25 /tmp/ci_fulfill.log; }
assert_min /tmp/ci_fulfill.log 43 "履约链路端到端"

echo "=== Job 7b/7: 造单场景矩阵端到端（7 场景 × 识别验证）==="
# 复盘补齐：mock-platform 场景库有 10 个场景，此前仅 normal 被端到端验证
# 覆盖 normal/multi_item/big_amount/out_of_stock/address_abnormal/unbound_item/buyer_message
# ⚠ 必须排在「履约链路端到端」之后——场景矩阵会清理自己的基础数据，
#    提前跑会删掉履约 E2E 依赖的仓/物料/库存
(cd "$ROOT/backend" && "$PY" -m app.scripts.scenario_matrix_e2e --with-mock >/tmp/ci_scenariomatrix.log 2>&1) \
  && ok "造单场景矩阵（$(grep -oE '合计：[0-9]+/[0-9]+ 项通过' /tmp/ci_scenariomatrix.log | tail -1)）" \
  || { bad "造单场景矩阵"; tail -25 /tmp/ci_scenariomatrix.log; }
assert_min /tmp/ci_scenariomatrix.log 35 "造单场景矩阵"

echo "=== Job 7c/7: M2 gate③ 三类异常单人工处置闭环 ==="
# M2 里程碑正式验收点：缺货 / 未绑定商品 / 地址异常 三类异常单的
# 「落单 → 自动分派 → 人工处置 → 闭环 → 审单原因清零」全链路。
(cd "$ROOT/backend" && "$PY" -m app.scripts.m2_gate3_e2e >/tmp/ci_m2gate3.log 2>&1) \
  && ok "M2 gate③ 异常单处置闭环（$(grep -oE '合计：[0-9]+/[0-9]+ 项通过' /tmp/ci_m2gate3.log | tail -1)）" \
  || { bad "M2 gate③ 异常单处置闭环"; tail -25 /tmp/ci_m2gate3.log; }
assert_min /tmp/ci_m2gate3.log 36 "M2 gate③ 异常单处置闭环"

echo "=== Job 8/8: W7 通道端到端（推仓→WMS 回放→回传→settle→发货确认→平台回传）==="
# 自起 mock-wms（9001）与 mock-platform（9000）——CI 库需要真实 WMS 才能跑通推仓链路
MOCK_WMS_PID=""; MOCK_PLATFORM_PID=""
if ! "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9001)); s.close()" >/dev/null 2>&1; then
  (cd "$ROOT/mocks/wms" && nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 9001 >/tmp/ci_mockwms_srv.log 2>&1 &) 
  MOCK_WMS_PID="started"
  for i in $(seq 1 20); do
    "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9001)); s.close()" >/dev/null 2>&1 && break
    sleep 1
  done
fi
if ! "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9000)); s.close()" >/dev/null 2>&1; then
  (cd "$ROOT/mocks/platform" && nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 9000 >/tmp/ci_mockplat_srv.log 2>&1 &)
  MOCK_PLATFORM_PID="started"
  for i in $(seq 1 20); do
    "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9000)); s.close()" >/dev/null 2>&1 && break
    sleep 1
  done
fi
MOCK_WMS_UP=0; MOCK_PLATFORM_UP=0
"$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9001)); s.close()" >/dev/null 2>&1 && MOCK_WMS_UP=1
"$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9000)); s.close()" >/dev/null 2>&1 && MOCK_PLATFORM_UP=1
if [ "$MOCK_WMS_UP" = "1" ]; then
  (cd "$ROOT/backend" && "$PY" -m app.scripts.wms_channel_e2e >/tmp/ci_wms.log 2>&1) \
    && ok "W7 通道端到端（$(grep -oE '合计：[0-9]+/[0-9]+ 项通过' /tmp/ci_wms.log | tail -1)）" \
    || { bad "W7 通道端到端"; tail -25 /tmp/ci_wms.log; }
assert_min /tmp/ci_wms.log 23 "W7 通道端到端"
else
  echo "  ⚠ 跳过 W7 通道端到端（mock-wms 未启动）"
fi
if [ "$MOCK_PLATFORM_UP" = "1" ]; then
  (cd "$ROOT/backend" && "$PY" -m app.scripts.writeback_e2e >/tmp/ci_wb.log 2>&1) \
    && ok "W7 平台回传端到端（$(grep -oE '合计：[0-9]+/[0-9]+ 项通过' /tmp/ci_wb.log | tail -1)）" \
    || { bad "W7 平台回传端到端"; tail -25 /tmp/ci_wb.log; }
assert_min /tmp/ci_wb.log 12 "W7 平台回传端到端"
else
  echo "  ⚠ 跳过 W7 平台回传端到端（mock-platform 未启动）"
fi

echo "=== Job 4/4: Frontend (type-check + build) ==="
(cd "$ROOT/frontend" && ./node_modules/.bin/vue-tsc --noEmit >/tmp/ci_tsc.log 2>&1) \
  && ok "type-check" || { bad "type-check"; tail -8 /tmp/ci_tsc.log; }
# 构建前先清 dist：vite 会清空 outDir，本机偶发被占用导致误报（CI 全新 checkout 无此问题）
(cd "$ROOT/frontend" && rm -rf dist >/dev/null 2>&1; ./node_modules/.bin/vue-tsc -b >/tmp/ci_tsb.log 2>&1 && ./node_modules/.bin/vite build >/tmp/ci_vite.log 2>&1) \
  && ok "build（vue-tsc -b + vite build）" || { bad "build"; tail -8 /tmp/ci_tsb.log; tail -5 /tmp/ci_vite.log; }

docker rm -f ci_ci_mysql ci_ci_redis >/dev/null 2>&1
echo "=========================================="
echo "通过 $PASS 项 / 失败 $FAIL 项"
[ "$FAIL" = "0" ] && echo "✅ CI 等价流程全绿，可安全推送" || echo "❌ 存在失败项，推送前必须修复"
exit $FAIL
