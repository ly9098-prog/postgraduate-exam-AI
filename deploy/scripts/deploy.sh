#!/bin/bash
# === 2240AI 部署脚本 ===
# 用法: ./deploy/scripts/deploy.sh [--skip-backup]
set -euo pipefail

DEPLOY_DIR="/opt/2240ai-v2"
SKIP_BACKUP=false

for arg in "$@"; do
    case $arg in
        --skip-backup) SKIP_BACKUP=true ;;
    esac
done

echo "=== 2240AI 部署开始 [$(date)] ==="
echo "部署目录: $DEPLOY_DIR"

cd "$DEPLOY_DIR" || { echo "错误: $DEPLOY_DIR 不存在"; exit 1; }

# 1. 备份
if [ "$SKIP_BACKUP" = false ]; then
    echo "[1/5] 执行数据库备份 ..."
    bash deploy/scripts/backup.sh || echo "⚠ 备份失败，继续部署"
else
    echo "[1/5] 跳过备份 (--skip-backup)"
fi

# 2. 拉取代码
echo "[2/5] 拉取最新代码 ..."
git pull origin main

# 3. 构建镜像
echo "[3/5] 构建 Docker 镜像 ..."
docker compose -f deploy/docker-compose.yml build --pull

# 4. 运行迁移
echo "[4/5] 运行数据库迁移 ..."
docker compose -f deploy/docker-compose.yml run --rm app alembic upgrade head

# 5. 重启服务
echo "[5/5] 重启服务 ..."
docker compose -f deploy/docker-compose.yml down --remove-orphans
docker compose -f deploy/docker-compose.yml up -d

echo ""
echo "=== 部署完成 [$(date)] ==="
echo "健康检查:"
sleep 3
bash deploy/scripts/health-check.sh || true
