#!/bin/bash
# === 22408AI PostgreSQL 自动备份 ===
# 建议 cron 每日执行: 0 3 * * * /opt/22408-ai/deploy/scripts/backup.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/data/backups/postgres}"
DB_NAME="${POSTGRES_DB:-postgraduate}"
DB_USER="${POSTGRES_USER:-postgraduate}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] 开始备份 $DB_NAME ..."

pg_dump -h localhost -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

BACKUP_SIZE=$(du -h "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz" | cut -f1)
echo "[$(date)] 备份完成: ${DB_NAME}_${TIMESTAMP}.sql.gz ($BACKUP_SIZE)"

# 清理过期备份
DELETED=$(find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] 已清理 $DELETED 个过期备份 (>${RETENTION_DAYS}天)"
fi
