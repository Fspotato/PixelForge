COMPOSE_DEV = docker compose -p ai-service-framework-dev -f docker/docker-compose.dev.yml
COMPOSE_STAGE = docker compose -p ai-service-framework-stage -f docker/docker-compose.stage.yml
COMPOSE_PROD = docker compose -p ai-service-framework-prod -f docker/docker-compose.prod.yml

.PHONY: git-sync
.PHONY: dev dev-up dev-down dev-logs dev-create-superuser
.PHONY: stage stage-up stage-down stage-logs stage-create-superuser
.PHONY: prod prod-up prod-down prod-logs prod-create-superuser

git-sync:
	git fetch --all --prune
	git pull --ff-only

dev:
	$(MAKE) git-sync
	$(MAKE) dev-down
	$(MAKE) dev-up

dev-up:
	$(COMPOSE_DEV) up --build -d

dev-down:
	$(COMPOSE_DEV) down --remove-orphans

dev-logs:
	$(COMPOSE_DEV) logs -f web celery-worker celery-beat postgres redis frontend

dev-create-superuser:
	$(COMPOSE_DEV) exec web python /scripts/create_superuser.py

stage:
	$(MAKE) git-sync
	$(MAKE) stage-down
	$(MAKE) stage-up

stage-up:
	$(COMPOSE_STAGE) up --build -d

stage-down:
	$(COMPOSE_STAGE) down --remove-orphans

stage-logs:
	$(COMPOSE_STAGE) logs -f web celery-worker celery-beat postgres redis

stage-create-superuser:
	$(COMPOSE_STAGE) exec web python /scripts/create_superuser.py

prod:
	$(MAKE) git-sync
	$(MAKE) prod-down
	$(MAKE) prod-up

prod-up:
	$(COMPOSE_PROD) up --build -d

prod-down:
	$(COMPOSE_PROD) down --remove-orphans

prod-logs:
	$(COMPOSE_PROD) logs -f web celery-worker celery-beat postgres redis

prod-create-superuser:
	$(COMPOSE_PROD) exec web python /scripts/create_superuser.py