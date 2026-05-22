#!/usr/bin/env bash
# 2240AI — 部署脚本
# 使用方法:
#   首次部署:  sudo bash deploy/deploy.sh init
#   日常更新:  sudo bash deploy/deploy.sh update
#   仅构建:    sudo bash deploy/deploy.sh build

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="docker-compose.prod.yml"

# ---------- 颜色 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ---------- 前置检查 ----------
check_prereqs() {
  command -v docker >/dev/null 2>&1 || error "需要安装 Docker"
  command -v docker-compose >/dev/null 2>&1 || command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || error "需要安装 docker-compose"
  [ -f .env ] || error ".env 文件不存在！请从 .env.example 复制并填写生产配置"
}

# ---------- 构建 ----------
do_build() {
  info "构建 Docker 镜像..."
  docker compose -f "$COMPOSE_FILE" build --no-cache app
  info "构建完成"
}

# ---------- 启动 ----------
do_up() {
  info "启动服务..."
  docker compose -f "$COMPOSE_FILE" up -d
  info "服务已启动"
}

# ---------- 初始化数据库 ----------
do_migrate() {
  info "运行数据库迁移..."
  docker compose -f "$COMPOSE_FILE" exec -T app alembic upgrade head
  info "迁移完成"
}

# ---------- 检查状态 ----------
do_status() {
  docker compose -f "$COMPOSE_FILE" ps
  echo ""
  info "健康检查:"
  curl -sf https://your-domain.com/health 2>/dev/null || warn "无法访问健康检查（可能尚未配置域名）"
}

# ---------- 首次部署 ----------
do_init() {
  check_prereqs
  do_build
  do_up
  info "等待数据库就绪..."
  sleep 5
  do_migrate
  info "=== 首次部署完成 ==="
  echo "接下来请："
  echo "  1. 配置域名 DNS 指向服务器 IP"
  echo "  2. 配置 HTTPS (certbot)"
  echo "  3. 检查 docker compose ps 确认所有服务运行中"
}

# ---------- 日常更新 ----------
do_update() {
  check_prereqs
  info "拉取最新代码..."
  git pull
  do_build
  info "重启服务..."
  docker compose -f "$COMPOSE_FILE" up -d --no-deps app
  do_migrate
  info "=== 更新完成 ==="
}

# ---------- 主入口 ----------
case "${1:-help}" in
  init)   do_init ;;
  update) do_update ;;
  build)  check_prereqs; do_build ;;
  status) check_prereqs; do_status ;;
  migrate) check_prereqs; do_migrate ;;
  *)
    echo "使用方法: $0 {init|update|build|status|migrate}"
    echo ""
    echo "  init    首次部署（构建 + 启动 + 迁移）"
    echo "  update  日常更新（git pull + 构建 + 重启）"
    echo "  build   仅重新构建镜像"
    echo "  status  查看服务状态"
    echo "  migrate 运行数据库迁移"
    ;;
esac
