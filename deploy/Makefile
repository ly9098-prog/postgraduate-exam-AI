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

backup:
	bash deploy/scripts/backup.sh

deploy update:
	bash deploy/scripts/deploy.sh update

migrate:
	bash deploy/scripts/deploy.sh migrate

health-check:
	bash deploy/scripts/health-check.sh
