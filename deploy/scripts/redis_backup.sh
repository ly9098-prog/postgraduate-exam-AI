#!/usr/bin/env bash
# 22408AI — Redis 一致性备份（生产 Docker 模式）
#
# 用法：
#   bash deploy/scripts/redis_backup.sh backup    # 生成一份 RDB 快照备份
#   bash deploy/scripts/redis_backup.sh list      # 列出已有备份
#
# 说明：
# - Redis 已在持久卷中开启 AOF；本脚本额外保留按时间留存的原生 RDB 快照，
#   用于误操作/灾备恢复，不能替代 AOF。
# - 优先使用 BGSAVE，避免阻塞主线程；备份默认写入宿主机目录，不依赖
#   Redis 命名卷或容器内路径。
# - 如果备份目录位于 Redis 容器内，使用临时 Redis 容器读取数据卷，避免
#   `docker compose exec` 在宿主机和容器目录之间混用路径。
# - Redis 未运行或不可达时退出码非 0，方便 cron/告警感知。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="deploy/docker-compose.prod.yml"
ENV_FILE="backend/.env"
REDIS_SERVICE="redis"
REDIS_CONTAINER="${REDIS_CONTAINER:-deploy-redis-1}"
BACKUP_DIR="${REDIS_BACKUP_DIR:-${PROJECT_DIR}/redis_backups}"
RETENTION_DAYS="${REDIS_BACKUP_RETENTION_DAYS:-14}"
REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"
REDIS_VOLUME="${REDIS_VOLUME:-}"
REDIS_DATA_DIR="${REDIS_DATA_DIR:-/data}"
HELPER_CONTAINER="${REDIS_HELPER_CONTAINER:-deploy-redis-backup-helper}"
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

resolve_redis_volume() {
  local mounted_inspect
  mounted_inspect="$(
    docker inspect "$REDIS_CONTAINER" --format '{{json .Mounts}}' 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    for item in data:
        if item.get("Destination") == "/data" and item.get("Type") == "volume":
            print(item.get("Name", ""))
            break
except Exception:
    pass
' 2>/dev/null || true
  )"
  if [ -n "$mounted_inspect" ]; then
    REDIS_VOLUME="$mounted_inspect"
  fi
  if [ -z "$REDIS_VOLUME" ]; then
    REDIS_VOLUME="${COMPOSE_PROJECT_NAME:-deploy}_redisdata_prod"
  fi
  if ! docker volume inspect "$REDIS_VOLUME" >/dev/null 2>&1; then
    local mounted_volume
    mounted_volume="$(
      compose config --format json 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    for item in data.get("services", {}).get("redis", {}).get("volumes", []):
        if item.get("target") == "/data":
            print(item.get("source", ""))
            break
except Exception:
    pass
' 2>/dev/null || true
    )"
    if [ -n "$mounted_volume" ] && docker volume inspect "$mounted_volume" >/dev/null 2>&1; then
      REDIS_VOLUME="$mounted_volume"
    fi
  fi
  docker volume inspect "$REDIS_VOLUME" >/dev/null 2>&1 \
    || error "找不到 Redis 数据卷: $REDIS_VOLUME（可用 REDIS_VOLUME=... 指定）"
}

require_runtime() {
  command -v docker >/dev/null 2>&1 || error "需要安装 Docker"
  docker compose version >/dev/null 2>&1 || error "需要安装 Docker Compose v2"
  [ -f "$COMPOSE_FILE" ] || error "$COMPOSE_FILE 文件不存在"
  [ -f "$ENV_FILE" ] || error "$ENV_FILE 文件不存在"
  mkdir -p "$BACKUP_DIR"
  redis_cli ping >/dev/null 2>&1 || error "Redis 不可达，终止备份"
}

do_backup() {
  require_runtime

  info "触发 Redis BGSAVE ..."
  local last_save
  last_save="$(redis_cli LASTSAVE 2>/dev/null | tr -d '\r')"
  redis_cli BGSAVE >/dev/null

  # 等待 RDB 落盘：LASTSAVE 增大说明新快照完成。
  local waited=0
  while [ "$waited" -lt 120 ]; do
    sleep 2
    waited=$((waited + 2))
    local now_save
    now_save="$(redis_cli LASTSAVE 2>/dev/null | tr -d '\r')"
    if [ -n "$now_save" ] && [ "$now_save" != "$last_save" ]; then
      break
    fi
  done
  if [ "$now_save" = "$last_save" ]; then
    warn "等待 BGSAVE 超过 ${waited}s；仍尝试复制当前 RDB"
  fi

  local redis_dir redis_file
  redis_dir="$(redis_cli CONFIG GET dir | tail -n1 | tr -d '\r')"
  redis_file="$(redis_cli CONFIG GET dbfilename | tail -n1 | tr -d '\r')"
  [ -n "$redis_dir" ] || error "无法读取 Redis dir"
  [ -n "$redis_file" ] || error "无法读取 Redis dbfilename"

  local target
  local tmp_target
  target="${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
  tmp_target="${target}.tmp"
  info "从 Redis 数据卷复制 ${redis_dir}/${redis_file} -> ${target}"

  resolve_redis_volume
  docker rm -f "$HELPER_CONTAINER" >/dev/null 2>&1 || true
  cleanup_helper() {
    docker rm -f "$HELPER_CONTAINER" >/dev/null 2>&1 || true
  }
  trap cleanup_helper EXIT

  docker run --rm \
    --name "$HELPER_CONTAINER" \
    -v "${REDIS_VOLUME}:${REDIS_DATA_DIR}:ro" \
    --entrypoint sh \
    "$REDIS_IMAGE" \
    -ceu '
      redis_dir="$1"
      redis_file="$2"
      source="${redis_dir}/${redis_file}"
      [ -f "$source" ] || { echo "RDB 文件不存在: $source" >&2; exit 1; }
      cat "$source"
    ' sh "$redis_dir" "$redis_file" > "$tmp_target"

  local size
  size="$(du -h "$tmp_target" | cut -f1)"
  # 校验 RDB 文件头，防止把错误输出当成备份保存。
  head -c 5 "$tmp_target" | grep -q 'REDIS' || error "备份文件头非法，已保留待排查: $tmp_target"
  chmod 600 "$tmp_target"
  mv "$tmp_target" "$target"
  info "Redis 备份完成: ${target} (${size})"

  if [ "${RETENTION_DAYS}" -gt 0 ]; then
    local deleted
    deleted="$(find "$BACKUP_DIR" -name 'redis_*.rdb' -mtime +"${RETENTION_DAYS}" -delete -print | wc -l)"
    if [ "$deleted" -gt 0 ]; then
      info "已清理 ${deleted} 个过期 Redis 备份 (>${RETENTION_DAYS} 天)"
    fi
  fi
}

do_list() {
  [ -d "$BACKUP_DIR" ] || { warn "备份目录不存在: $BACKUP_DIR"; return 0; }
  ls -lh "$BACKUP_DIR"/redis_*.rdb 2>/dev/null || warn "暂无 Redis 备份"
}

case "${1:-help}" in
  backup) do_backup ;;
  list)   do_list ;;
  *)
    echo "用法: $0 {backup|list}"
    echo "环境变量: REDIS_BACKUP_DIR(default ${BACKUP_DIR}) REDIS_BACKUP_RETENTION_DAYS(default ${RETENTION_DAYS})"
    ;;
esac
