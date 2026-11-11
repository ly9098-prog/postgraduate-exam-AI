#!/bin/bash
# Legacy database initialization script.
# Current production migration entry: bash deploy/scripts/deploy.sh migrate
set -euo pipefail

echo "=== 22408AI 数据库初始化 ==="

DB_USER="${POSTGRES_USER:-postgraduate}"
DB_NAME="${POSTGRES_DB:-postgraduate}"

echo "创建数据库 $DB_NAME ..."
psql -U "$DB_USER" -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    psql -U "$DB_USER" -c "CREATE DATABASE $DB_NAME"

echo "启用扩展 ..."
psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto"

echo "运行迁移 ..."
cd /app && alembic upgrade head

echo "数据库初始化完成"
