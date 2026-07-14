.PHONY: up down restart logs status build backup deploy update migrate health-check

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

# 生产 PostgreSQL 备份（Python 脚本）
# 也支持 Docker 模式：$(COMPOSE) run --rm backup
backup:
	cd $(dir $(lastword $(MAKEFILE_LIST))).. && python scripts/postgres_backup.py

deploy update:
	bash deploy/scripts/deploy.sh update

migrate:
	bash deploy/scripts/deploy.sh migrate

health-check:
	bash deploy/scripts/health-check.sh
