#!/usr/bin/env bash
# 22408AI — Redis RDB 恢复（AOF-safe restore）
#
# 用法：
#   bash deploy/scripts/redis_restore.sh /opt/22408-ai/redis_backups/redis_YYYYmmdd_HHMMSS.rdb
#
# 为什么不能直接替换 /data/dump.rdb 后 restart：
# Redis 已开启 appendonly，启动时会优先加载 appendonlydir，而不是 dump.rdb。
# 如果只复制 RDB 就重启，可能加载到空 AOF / 旧 AOF，表现为 DBSIZE=0。
#
# 安全流程：
#   1. 校验输入是 RDB 文件；
#   2. 停止生产 Redis，保留旧数据目录为带时间戳快照；
#   3. 清空当前数据目录中的 appendonlydir / dump.rdb；
#   4. 以 appendonly no + 临时端口启动一次性 helper，令其从 RDB 加载；
#   5. 在 helper 中确认 DBSIZE > 0，再开启 appendonly 并等待 AOF 重写完成；
#   6. 停止 helper，启动生产 Redis，校验 PING / DBSIZE / 持久化状态。
#
# 注意：该脚本会停 Redis 并替换其数据目录，只能在维护窗口执行。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="deploy/docker-compose.prod.yml"
ENV_FILE="backend/.env"
REDIS_SERVICE="redis"
REDIS_CONTAINER="${REDIS_CONTAINER:-deploy-redis-1}"
REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"
REDIS_DATA_DIR="${REDIS_DATA_DIR:-/data}"
REDIS_VOLUME="${REDIS_VOLUME:-deploy_redisdata_prod}"
HELPER_CONTAINER="${REDIS_HELPER_CONTAINER:-deploy-redis-restore-helper}"
HELPER_PORT="${REDIS_HELPER_PORT:-6390}"
PRESERVE_ROOT="${REDIS_RESTORE_PRESERVE_DIR:-${PROJECT_DIR}/redis_backups/restore-snapshots}"
PRESERVE_DIR=""
REDIS_STOPPED=0
PRODUCTION_STARTED=0
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

redis_cli() {
  compose exec -T "$REDIS_SERVICE" redis-cli "$@"
}

helper_cli() {
  docker exec -i "$HELPER_CONTAINER" redis-cli -p "$HELPER_PORT" "$@"
}

cleanup() {
  local exit_code=$?
  docker rm -f "$HELPER_CONTAINER" >/dev/null 2>&1 || true
  # Never leave production Redis stopped after a restore attempt. The data
  # directory contains either the restored RDB or the preserved old data, so
  # restarting here is preferable to an extended Redis outage.
  if [ "$REDIS_STOPPED" -eq 1 ] && [ "$PRODUCTION_STARTED" -eq 0 ]; then
    warn "恢复流程异常退出，尝试重新启动生产 Redis（旧数据快照: ${PRESERVE_DIR:-未创建}）"
    compose up -d "$REDIS_SERVICE" >/dev/null 2>&1 || true
  fi
  if [ "$exit_code" -ne 0 ] && [ -n "$PRESERVE_DIR" ]; then
    warn "恢复失败；旧 Redis 数据目录快照保留在: $PRESERVE_DIR"
  fi
  return "$exit_code"
}

require_runtime() {
  command -v docker >/dev/null 2>&1 || error "需要安装 Docker"
  docker compose version >/dev/null 2>&1 || error "需要安装 Docker Compose v2"
  [ -f "$COMPOSE_FILE" ] || error "$COMPOSE_FILE 文件不存在"
  [ -f "$ENV_FILE" ] || error "$ENV_FILE 文件不存在"
}

resolve_volume() {
  # Prefer the volume actually mounted by the rendered compose file. The
  # default supports the current production project name (deploy_*).
  local mounted
  mounted="$(compose config --format json 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    volumes = data.get("services", {}).get("redis", {}).get("volumes", [])
    for item in volumes:
        if item.get("target") == "/data":
            print(item.get("source", ""))
            break
except Exception:
    pass
' 2>/dev/null || true)"
  if [ -n "$mounted" ]; then
    REDIS_VOLUME="$mounted"
  fi
  docker volume inspect "$REDIS_VOLUME" >/dev/null 2>&1 \
    || error "找不到 Redis 数据卷: $REDIS_VOLUME（可用 REDIS_VOLUME=... 指定）"
}

validate_backup() {
  local backup="$1"
  [ -f "$backup" ] || error "备份文件不存在: $backup"
  [ -s "$backup" ] || error "备份文件为空: $backup"
  head -c 5 "$backup" | grep -q 'REDIS' || error "不是有效 RDB 文件（缺少 REDIS 头）: $backup"
}

stop_redis() {
  info "停止生产 Redis（仅停止容器，不删除命名卷）..."
  compose stop "$REDIS_SERVICE" >/dev/null
}

preserve_old_data() {
  PRESERVE_DIR="${PRESERVE_ROOT}/old-data-${TIMESTAMP}"
  mkdir -p "$PRESERVE_DIR"
  info "将当前 Redis 数据目录快照保存到 $PRESERVE_DIR ..."
  docker run --rm \
    -v "$REDIS_VOLUME:$REDIS_DATA_DIR" \
    -v "$PRESERVE_DIR:/backup" \
    "$REDIS_IMAGE" \
    sh -c "cp -a '$REDIS_DATA_DIR/.' /backup/"
}

install_backup_rdb() {
  local backup="$1"
  info "清空数据卷中的 AOF/RDB，并复制备份 RDB ..."
  # 该卷只属于 Redis；仍先保留 old-data 快照，再删除旧 AOF，避免 AOF
  # 在下次启动时覆盖从 RDB 恢复出的数据。
  docker run --rm \
    -v "$REDIS_VOLUME:$REDIS_DATA_DIR" \
    -v "$backup:$REDIS_DATA_DIR.dump.rdb:ro" \
    "$REDIS_IMAGE" \
    sh -c "rm -rf '$REDIS_DATA_DIR/appendonlydir' '$REDIS_DATA_DIR/dump.rdb' && cp '$REDIS_DATA_DIR.dump.rdb' '$REDIS_DATA_DIR/dump.rdb' && chown -R 999:999 '$REDIS_DATA_DIR'"
}

start_helper() {
  docker rm -f "$HELPER_CONTAINER" >/dev/null 2>&1 || true
  info "启动临时 Redis helper（appendonly=no，从 RDB 加载）..."
  docker run -d --name "$HELPER_CONTAINER" \
    -p "127.0.0.1:${HELPER_PORT}:6379" \
    -v "$REDIS_VOLUME:$REDIS_DATA_DIR" \
    "$REDIS_IMAGE" \
    redis-server --appendonly no --dir "$REDIS_DATA_DIR" --dbfilename dump.rdb >/dev/null

  local waited=0
  until helper_cli PING >/dev/null 2>&1; do
    sleep 1
    waited=$((waited + 1))
    [ "$waited" -lt 30 ] || error "临时 Redis helper 启动超时"
  done
}

verify_restored_data() {
  local dbsize
  dbsize="$(helper_cli DBSIZE | tr -d '\r')"
  info "RDB 加载后 DBSIZE=${dbsize}"
  case "$dbsize" in
    ''|*[!0-9]*) error "无法读取恢复后的 DBSIZE" ;;
  esac
  [ "$dbsize" -gt 0 ] || error "恢复后的 DBSIZE=0；已停止，不会覆盖生产 AOF"
}

rebuild_aof() {
  info "在 helper 中启用 AOF 并等待重写完成 ..."
  helper_cli CONFIG SET appendonly yes >/dev/null
  local waited=0
  local persistence
  while [ "$waited" -lt 120 ]; do
    persistence="$(helper_cli INFO persistence 2>/dev/null || true)"
    if printf '%s\n' "$persistence" \
      | grep -q 'aof_last_bgrewrite_status:ok' \
      && printf '%s\n' "$persistence" \
        | grep -q 'aof_rewrite_in_progress:0'; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  error "AOF 重写超时或状态异常，已保留 helper 供排查"
}

start_production() {
  info "停止 helper，启动生产 Redis ..."
  docker rm -f "$HELPER_CONTAINER" >/dev/null 2>&1 || true
  compose up -d "$REDIS_SERVICE" >/dev/null
  PRODUCTION_STARTED=1
  local waited=0
  until redis_cli PING >/dev/null 2>&1; do
    sleep 1
    waited=$((waited + 1))
    [ "$waited" -lt 45 ] || error "生产 Redis 启动超时"
  done
}

verify_production() {
  info "生产 Redis 恢复校验（PING / DBSIZE / INFO persistence）..."
  redis_cli PING
  redis_cli DBSIZE
  redis_cli INFO persistence | grep -E 'aof_enabled|aof_last_bgrewrite_status|rdb_last_bgsave_status' || true
  warn "原 Redis 数据目录快照保留在: $PRESERVE_DIR"
  warn "该目录仅作故障排查用途，确认恢复稳定后再由人工清理。"
}

main() {
  local backup="${1:-}"
  [ -n "$backup" ] || error "用法: $0 <backup.rdb>"
  trap cleanup EXIT
  require_runtime
  validate_backup "$backup"
  resolve_volume
  stop_redis
  REDIS_STOPPED=1
  preserve_old_data
  install_backup_rdb "$backup"
  start_helper
  verify_restored_data
  rebuild_aof
  start_production
  verify_production
  info "Redis 恢复完成"
}

case "${1:-help}" in
  help|-h|--help)
    echo "用法: $0 <backup.rdb>"
    echo "环境变量: REDIS_VOLUME(default ${REDIS_VOLUME}) REDIS_HELPER_PORT(default ${HELPER_PORT})"
    ;;
  *)
    main "${1:-}"
    ;;
esac
