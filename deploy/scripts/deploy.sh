#!/usr/bin/env bash
# 2240AI — 生产部署脚本
# 使用方法:
#   首次部署:  sudo bash deploy/scripts/deploy.sh init
#   日常更新:  sudo bash deploy/scripts/deploy.sh update
#   仅构建:    sudo bash deploy/scripts/deploy.sh build
#   显式迁移:  sudo bash deploy/scripts/deploy.sh migrate

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="deploy/docker-compose.prod.yml"
ENV_FILE="backend/.env"
HEALTH_HOST="${HEALTH_HOST:-xzshub.top}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

show_app_logs() {
  warn "app 最近日志如下："
  compose logs --tail=80 app || true
}

check_prereqs() {
  command -v docker >/dev/null 2>&1 || error "需要安装 Docker"
  docker compose version >/dev/null 2>&1 || error "需要安装 Docker Compose v2"
  docker info >/dev/null 2>&1 || error "Docker daemon 不可用"
  [ -f "$COMPOSE_FILE" ] || error "$COMPOSE_FILE 文件不存在"
  [ -f "$ENV_FILE" ] || error "$ENV_FILE 文件不存在！请在 backend/.env 中维护生产配置"
  local services
  services="$(compose config --services)"
  case "
$services
" in
    *"
app
"*) ;;
    *) error "compose 配置中未找到 app 服务" ;;
  esac
}

do_build() {
  info "构建 app 镜像（保留 Docker layer cache）..."
  compose build app
  info "构建完成"
}

do_build_admin() {
  info "构建 admin 前端镜像（保留 Docker layer cache）..."
  compose build admin
  info "admin 构建完成"
}

do_up() {
  info "启动服务..."
  compose up -d
  info "服务已启动"
}

do_update_app() {
  info "替换 app 服务（不重启 postgres/redis/nginx）..."
  compose up -d --no-deps app
  info "app 服务已替换"
  # Also replace scheduler (same image, different command)
  info "替换 scheduler 服务..."
  compose up -d --no-deps scheduler 2>/dev/null || warn "scheduler 服务不存在或启动失败（export 功能不可用）"
  info "scheduler 服务已替换"
}

do_update_admin() {
  info "替换 admin 前端服务..."
  compose up -d --no-deps admin
  info "admin 服务已替换"
}

do_admin_health_check() {
  info "检查 admin 前端健康状态..."
  local attempt
  for attempt in 1 2 3 4 5; do
    if compose exec -T admin sh -c "wget -qO- http://127.0.0.1:3000/ >/dev/null 2>&1"; then
      info "admin 前端健康检查通过"
      return 0
    fi
    if [ "$attempt" -eq 5 ]; then
      warn "admin 前端健康检查未通过"
      compose logs --tail=30 admin || true
      return 1
    fi
    sleep 3
  done
}

do_migrate() {
  check_prereqs
  info "运行数据库迁移..."
  compose exec -T app alembic upgrade head
  info "迁移完成"
}

do_scheduler_health_check() {
  info "检查 scheduler 服务健康状态..."
  local attempt
  for attempt in 1 2 3 4 5; do
    if compose exec -T app python -c "
import urllib.request, json
resp = urllib.request.urlopen('http://localhost:8000/api/v1/exports/health', timeout=5)
data = json.loads(resp.read())
assert data.get('processor_running') is True, 'Processor not running: ' + str(data)
assert data.get('status') == 'ok', 'Status not ok: ' + str(data)
" >/dev/null 2>&1; then
      info "scheduler 健康检查通过（processor_running=true）"
      return 0
    fi
    sleep 3
  done
  warn "scheduler 健康检查未通过，请检查 scheduler 日志"
  compose logs --tail=20 scheduler || true
  return 1
}

do_update_scheduler() {
  check_prereqs
  do_build
  info "替换 scheduler 服务..."
  compose up -d --no-deps scheduler
  do_scheduler_health_check || warn "scheduler 健康检查未通过"
  info "=== scheduler 更新完成 ==="
}

do_health_check() {
  info "检查 app 容器内健康接口..."
  local attempt
  for attempt in 1 2 3 4 5; do
    if compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" >/dev/null 2>&1; then
      break
    fi

    if [ "$attempt" -eq 5 ]; then
      compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" >/dev/null || {
        show_app_logs
        return 1
      }
    fi

    sleep 3
  done

  if command -v curl >/dev/null 2>&1; then
    info "检查 nginx 本机 HTTPS 健康接口..."
    curl -skf -H "Host: $HEALTH_HOST" https://127.0.0.1/health >/dev/null || warn "nginx HTTPS 健康检查未通过"
  else
    warn "未安装 curl，跳过 nginx HTTPS 健康检查"
  fi
}

do_status() {
  check_prereqs
  compose ps
  echo ""
  do_health_check || warn "健康检查未通过"
  echo ""
  do_scheduler_health_check || warn "scheduler 健康检查未通过（export 功能不可用）"
}

do_init() {
  check_prereqs
  do_build
  do_up
  info "等待数据库就绪..."
  sleep 5
  do_migrate
  do_health_check
  do_scheduler_health_check || warn "scheduler 健康检查未通过（export 功能可能不可用）"
  info "=== 首次部署完成 ==="
  echo "接下来请："
  echo "  1. 配置域名 DNS 指向服务器 IP"
  echo "  2. 配置 HTTPS 证书"
  echo "  3. 检查 docker compose ps 确认所有服务运行中"
}

do_update() {
  check_prereqs
  do_build
  do_update_app
  do_health_check || error "更新后健康检查失败；请查看上方 app 日志，必要时回滚上一版本代码后重新执行 app 更新"
  do_scheduler_health_check || warn "scheduler 健康检查未通过（export 功能可能不可用）"
  info "=== 更新完成（未执行 git pull，未执行数据库迁移） ==="
}

do_update_all() {
  check_prereqs
  do_build
  do_build_admin
  do_update_app
  do_update_admin
  do_health_check || error "更新后 app 健康检查失败"
  do_admin_health_check || warn "admin 前端健康检查未通过，请检查日志"
  do_scheduler_health_check || warn "scheduler 健康检查未通过（export 功能可能不可用）"
  info "=== 全量更新完成（app + admin + scheduler，未执行 git pull，未执行数据库迁移） ==="
}

do_backup() {
  check_prereqs
  info "执行 PostgreSQL 备份（Docker 模式）..."
  compose run --rm backup
  info "=== 备份完成 ==="
}

case "${1:-help}" in
  init)         do_init ;;
  update)       do_update ;;
  update-admin) check_prereqs; do_build_admin; do_update_admin; do_admin_health_check || warn "admin 前端健康检查未通过" ;;
  update-scheduler) do_update_scheduler ;;
  update-all)   do_update_all ;;
  build)        check_prereqs; do_build ;;
  build-admin)  check_prereqs; do_build_admin ;;
  backup)       do_backup ;;
  status)       do_status ;;
  migrate)      do_migrate ;;
  *)
    echo "使用方法: $0 {init|update|update-admin|update-scheduler|update-all|build|build-admin|backup|status|migrate}"
    echo ""
    echo "  init              首次部署（构建 + 启动 + 显式初始化迁移）"
    echo "  update            日常更新（缓存构建 + 替换 app + scheduler，不 git pull，不默认迁移）"
    echo "  update-admin      仅更新 admin 前端（构建 + 替换 admin 服务）"
    echo "  update-scheduler  仅更新 scheduler（构建 + 替换 scheduler 服务）"
    echo "  update-all        全量更新（app + admin + scheduler，不 git pull，不默认迁移）"
    echo "  build             仅重新构建 app 镜像"
    echo "  build-admin       仅重新构建 admin 前端镜像"
    echo "  backup            执行 PostgreSQL 备份（Docker 模式）"
    echo "  status        查看服务状态和健康检查"
    echo "  migrate       显式运行数据库迁移"
    ;;
esac
