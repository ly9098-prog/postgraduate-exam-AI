.PHONY: up down restart logs status build backup deploy health-check

# === 生产 ===

up:
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

restart:
	docker compose -f deploy/docker-compose.yml restart

logs:
	docker compose -f deploy/docker-compose.yml logs -f --tail=100

status:
	docker compose -f deploy/docker-compose.yml ps

build:
	docker compose -f deploy/docker-compose.yml build

# === 开发 ===

dev-up:
	docker compose -f deploy/docker-compose.dev.yml up -d

dev-down:
	docker compose -f deploy/docker-compose.dev.yml down

dev-logs:
	docker compose -f deploy/docker-compose.dev.yml logs -f --tail=100

# === 运维 ===

backup:
	bash deploy/scripts/backup.sh

deploy:
	bash deploy/scripts/deploy.sh

health-check:
	bash deploy/scripts/health-check.sh

init-db:
	bash deploy/scripts/init-db.sh

# === SSL 证书 ===

cert-renew:
	docker compose -f deploy/docker-compose.yml run --rm certbot renew
	docker compose -f deploy/docker-compose.yml exec nginx nginx -s reload
