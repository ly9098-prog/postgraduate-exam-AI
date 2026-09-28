.PHONY: up down restart logs status build backup backup-redis redis-restore deploy update migrate health-check

COMPOSE = docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f --tail=100

status:
	$(COMPOSE) ps

build:
	$(COMPOSE) build app

# 生产备份：PostgreSQL + Redis RDB
backup:
	bash deploy/scripts/deploy.sh backup

# 仅备份 Redis
backup-redis:
	bash deploy/scripts/redis_backup.sh backup

# 从指定 RDB 安全恢复 Redis（会停止 Redis；BACKUP=...）
redis-restore:
	@test -n "$(BACKUP)" || (echo "用法: make redis-restore BACKUP=/path/to/redis.rdb"; exit 1)
	bash deploy/scripts/redis_restore.sh "$(BACKUP)"

deploy update:
	bash deploy/scripts/deploy.sh update

migrate:
	bash deploy/scripts/deploy.sh migrate

health-check:
	bash deploy/scripts/health-check.sh
