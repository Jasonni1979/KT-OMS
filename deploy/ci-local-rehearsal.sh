#!/usr/bin/env bash
# CI 本地全量复演（与 .github/workflows/ci.yml 四个 job 逐步骤等价）
# 用途：推送前自检，避免再收到失败邮件
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

echo "=== Job 1/4: Backend (ruff + mypy) ==="
(cd "$ROOT/backend" && "$PY" -m ruff check app tests --output-format=concise >/tmp/ci_ruff.log 2>&1) \
  && ok "ruff" || { bad "ruff"; tail -5 /tmp/ci_ruff.log; }
(cd "$ROOT/backend" && "$PY" -m mypy app --ignore-missing-imports >/tmp/ci_mypy.log 2>&1) \
  && ok "mypy" || { bad "mypy"; tail -5 /tmp/ci_mypy.log; }

echo "=== Job 2/4: Backend (pytest + MySQL/Redis) ==="
# 用独立 CI 库（自动选空闲端口），避免污染开发库 3308
docker rm -f ci_ci_mysql ci_test_mysql >/dev/null 2>&1
CI_PORT=3309
for p in 3309 3311 3312 3313; do
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

export KTOMS_MYSQL_HOST=127.0.0.1 KTOMS_MYSQL_PORT=$CI_PORT KTOMS_REDIS_URL="redis://127.0.0.1:6380/0"
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_org >/tmp/ci_seed1.log 2>&1) \
  && ok "seed_org" || { bad "seed_org"; tail -5 /tmp/ci_seed1.log; }
(cd "$ROOT/backend" && "$PY" -m app.scripts.seed_auth >/tmp/ci_seed2.log 2>&1) \
  && ok "seed_auth" || { bad "seed_auth"; tail -5 /tmp/ci_seed2.log; }
(cd "$ROOT/backend" && "$PY" -m pytest tests/ -q >/tmp/ci_pytest.log 2>&1) \
  && ok "pytest（$(grep -oE '[0-9]+ passed' /tmp/ci_pytest.log | tail -1)）" \
  || { bad "pytest"; tail -20 /tmp/ci_pytest.log; }

echo "=== Job 3/4: Mock Platform (pytest) ==="
(cd "$ROOT/mocks/platform" && "$PY" -m pytest tests/ -q >/tmp/ci_mock.log 2>&1) \
  && ok "mock pytest（$(grep -oE '[0-9]+ passed' /tmp/ci_mock.log | tail -1)）" \
  || { bad "mock pytest"; tail -15 /tmp/ci_mock.log; }

echo "=== Job 4/4: Frontend (type-check + build) ==="
(cd "$ROOT/frontend" && ./node_modules/.bin/vue-tsc --noEmit >/tmp/ci_tsc.log 2>&1) \
  && ok "type-check" || { bad "type-check"; tail -8 /tmp/ci_tsc.log; }
(cd "$ROOT/frontend" && ./node_modules/.bin/vue-tsc -b >/tmp/ci_tsb.log 2>&1 && ./node_modules/.bin/vite build >/tmp/ci_vite.log 2>&1) \
  && ok "build（vue-tsc -b + vite build）" || { bad "build"; tail -8 /tmp/ci_tsb.log; tail -5 /tmp/ci_vite.log; }

docker rm -f ci_ci_mysql >/dev/null 2>&1
echo "=========================================="
echo "通过 $PASS 项 / 失败 $FAIL 项"
[ "$FAIL" = "0" ] && echo "✅ CI 等价流程全绿，可安全推送" || echo "❌ 存在失败项，推送前必须修复"
exit $FAIL
