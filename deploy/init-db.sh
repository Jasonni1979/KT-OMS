#!/usr/bin/env bash
# KT-OMS 开发库初始化/重建脚本（M0.1）
# 用法: ./init-db.sh          # 导入 11 份 DDL（幂等：脚本自带 CREATE DATABASE IF NOT EXISTS，表已存在会报错跳过该文件）
#       ./init-db.sh --drop   # 先删除全部 oms_* schema 再导入（重建）
set -euo pipefail
cd "$(dirname "$0")"

MYSQL_PWD_VAL="ktoms_dev_2026"
SQL_DIR="../docs/database/sql"
CONTAINER="ktoms-mysql"

# ⚠️ 必须显式指定 --default-character-set=utf8mb4：
# 容器 locale 为 POSIX，mysql CLI 默认走 latin1/cp1252 连接字符集，
# 会把 SQL 文件里的 UTF-8 中文误解码后再按 UTF-8 写入 → 全库中文乱码
# （症状：'销售出库' 变成 'é”€å”®å‡ºåº"'；已用 tools/scan_mojibake.py 全量扫描修复）
CHARSET="--default-character-set=utf8mb4"

mx() { docker exec -i "$CONTAINER" mysql $CHARSET -uroot -p"$MYSQL_PWD_VAL" "$@"; }

if [[ "${1:-}" == "--drop" ]]; then
  echo ">>> 删除既有 oms_* schema..."
  for s in $(mx -N -e "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'oms_%'" 2>/dev/null); do
    mx -e "DROP DATABASE \`$s\`" && echo "  dropped $s"
  done
fi

echo ">>> 等待 MySQL 就绪..."
for i in $(seq 1 60); do
  if docker exec "$CONTAINER" mysqladmin ping -uroot -p"$MYSQL_PWD_VAL" --silent >/dev/null 2>&1; then
    # 初始化期 ping 通但可能仍在跑 init 流程，确认能查 information_schema
    if mx -N -e "SELECT 1" >/dev/null 2>&1; then echo "就绪(第${i}次探测)"; break; fi
  fi
  sleep 3
done

echo ">>> 按 D01→D11 顺序导入 DDL..."
pass=0; fail=0
for f in "$SQL_DIR"/*.sql; do
  if docker exec -i "$CONTAINER" mysql $CHARSET -uroot -p"$MYSQL_PWD_VAL" < "$f" >/tmp/ktoms_ddl_err.log 2>&1; then
    echo "  ✓ $(basename "$f")"; pass=$((pass+1))
  else
    echo "  ✗ $(basename "$f")"; grep -i "error" /tmp/ktoms_ddl_err.log | head -2; fail=$((fail+1))
  fi
done

echo ">>> 中文编码自检（抽样：单据类型目录）…"
mx -N -e "SELECT type_code, type_name FROM oms_stock.inv_io_bill_type WHERE type_code IN ('sale_out','purchase_in');" 2>/dev/null \
  | while read -r code name; do
      if [[ "$name" == *"销售出库"* || "$name" == *"采购入库"* ]]; then
        echo "  ✓ 编码正常: $code=$name"
      else
        echo "  ✗ 编码异常: $code=$name"
      fi
  done

echo ">>> 核验建表数..."
mx -N -e "SELECT table_schema, COUNT(*) FROM information_schema.tables WHERE table_schema LIKE 'oms_%' GROUP BY table_schema ORDER BY table_schema;" 2>/dev/null
TOTAL=$(mx -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema LIKE 'oms_%'" 2>/dev/null)
echo "----- 合计: $TOTAL 表 (预期 373) | 导入: 成功$pass 失败$fail"
[[ "$TOTAL" == "373" && "$fail" == "0" ]] && echo "✅ M0.1 数据库基建验收通过" || echo "⚠️ 与预期不符，请检查"
