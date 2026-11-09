# Short names for the common docker compose commands. Run `make` to list them.
COMPOSE := docker compose -f deploy/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help up infra down ps logs secret

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

# Compose reads deploy/.env automatically. Create it once with a random secret so the secret
# survives restarts (a new one each time would log everyone out). gitignored; never printed.
deploy/.env:
	@umask 077 && echo "JWT_SECRET=$$(openssl rand -hex 32)" > deploy/.env
	@echo "created deploy/.env with a random JWT_SECRET"

secret: deploy/.env ## Create deploy/.env with a JWT secret (done automatically by `make up`)

up: deploy/.env ## Build and start everything: dashboard :8080, API docs :8000/docs
	$(COMPOSE) up -d --build
	@echo "dashboard: http://localhost:8080   API docs: http://localhost:8000/docs"

infra: ## Start only db + mqtt (to run the apps from source)
	$(COMPOSE) up -d db mqtt

down: ## Stop everything, keep the data
	$(COMPOSE) stop

ps: ## Show each service's status and health
	$(COMPOSE) ps -a

logs: ## Follow logs (all services, or one: make logs s=ingestor)
	$(COMPOSE) logs -f --tail 50 $(s)
