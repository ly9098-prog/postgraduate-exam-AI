#!/usr/bin/env bash
# 2240AI — 数据库自动备份脚本
# 建议通过 cron 每天执行:
#   0 3 * * * /path/to/deploy/backup.sh

set -euo pipefail

BACKUP_DIR="/var/backups/2240ai"
DB_NAME="${DB_NAME:-postgraduate}"
DB_USER="${DB_USER:-pguser}"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 备份
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始备份 $DB_NAME ..."

# 从 docker-compose 的 db 容器备份
docker compose -f /home/lmh/projects/postgraduate-ai/docker-compose.prod.yml exec -T db \
  pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份完成: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# 清理过期备份
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +$RETENTION_DAYS -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已清理 ${RETENTION_DAYS} 天前的备份"

# 输出可用备份列表
echo "--- 现有备份: ---"
ls -lh "$BACKUP_DIR"
