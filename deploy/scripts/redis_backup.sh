#!/usr/bin/env bash
# 2240AI — Redis 一致性备份（生产 Docker 模式）
#
# 用法：
#   bash deploy/scripts/redis_backup.sh backup    # 生成一份 RDB 快照备份
#   bash deploy/scripts/redis_backup.sh list      # 列出已有备份
#
# 说明：
# - Redis 已在持久卷中开启 AOF；本脚本额外保留按时间留存的原生 RDB 快照，
#   用于误操作/灾备恢复，不能替代 AOF。
# - 优先使用 BGSAVE，避免阻塞主线程；随后用 CONFIG GET dir/dbfilename
#   定位真实文件，不假设路径。
# - Redis 未运行或不可达时退出码非 0，方便 cron/告警感知。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="deploy/docker-compose.prod.yml"
ENV_FILE="backend/.env"
REDIS_SERVICE="redis"
REDIS_CONTAINER="${REDIS_CONTAINER:-deploy-redis-1}"
BACKUP_DIR="${REDIS_BACKUP_DIR:-/data/backups/redis}"
RETENTION_DAYS="${REDIS_BACKUP_RETENTION_DAYS:-14}"
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

require_runtime() {
  command -v docker >/dev/null 2>&1 || error "需要安装 Docker"
  [ -f "$COMPOSE_FILE" ] || error "$COMPOSE_FILE 文件不存在"
  [ -f "$ENV_FILE" ] || error "$ENV_FILE 文件不存在"
  redis_cli ping >/dev/null 2>&1 || error "Redis 不可达，终止备份"
}

do_backup() {
  require_runtime
  mkdir -p "$BACKUP_DIR"

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

  local target="${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
  info "复制 ${redis_dir}/${redis_file} -> ${target}"
  compose exec -T "$REDIS_SERVICE" sh -c "cat '${redis_dir}/${redis_file}'" > "$target"

  local size
  size="$(du -h "$target" | cut -f1)"
  # 校验 RDB 文件头，防止把错误输出当成备份保存。
  head -c 5 "$target" | grep -q 'REDIS' || error "备份文件头非法，已保留待排查: $target"
  info "Redis 备份完成: ${target} (${size})"

  if [ "${RETENTION_DAYS}" -gt 0 ]; then
    local deleted
    deleted="$(find "$BACKUP_DIR" -name 'redis_*.rdb' -mtime +"${RETENTION_DAYS}" -delete -print | wc -l)"
    [ "$deleted" -gt 0 ] && info "已清理 ${deleted} 个过期 Redis 备份 (>${RETENTION_DAYS} 天)"
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
