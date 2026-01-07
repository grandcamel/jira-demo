.PHONY: dev build deploy logs health reset-sandbox clean otel-logs otel-reset check-token refresh-token \
	status-local health-local start-local stop-local restart-local queue-status-local queue-reset-local \
	logs-errors-local traces-errors-local run-scenario test-skill

# Load environment variables
ifneq (,$(wildcard ./secrets/.env))
    include ./secrets/.env
    export
endif

# Development
dev:
	@echo "Starting development environment..."
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build

dev-down:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

# Build
build:
	@echo "Building all containers..."
	docker-compose build
	docker build -t jira-demo-container:latest ./demo-container

# Deploy
deploy:
	@echo "Deploying to production..."
	docker-compose pull
	docker-compose build
	docker-compose down
	docker-compose up -d
	@echo "Waiting for services..."
	@sleep 5
	@$(MAKE) health

# Logs
logs:
	docker-compose logs -f --tail=100

logs-queue:
	docker-compose logs -f queue-manager

logs-nginx:
	docker-compose logs -f nginx

# Health check
health:
	@echo "Checking system health..."
	@curl -sf http://localhost/health > /dev/null && echo "Landing page: OK" || echo "Landing page: FAILED"
	@curl -sf http://localhost/api/status > /dev/null && echo "Queue manager: OK" || echo "Queue manager: FAILED"
	@docker-compose exec -T redis redis-cli ping > /dev/null && echo "Redis: OK" || echo "Redis: FAILED"

# JIRA Sandbox
reset-sandbox:
	@echo "Resetting JIRA sandbox..."
	docker-compose exec queue-manager python /opt/scripts/cleanup_demo_sandbox.py

seed-sandbox:
	@echo "Seeding JIRA sandbox..."
	docker-compose exec queue-manager python /opt/scripts/seed_demo_data.py

# Invite Management
invite:
	@docker-compose exec -T queue-manager node /app/invite-cli.js generate --expires $(or $(EXPIRES),48h) $(if $(TOKEN),--token "$(TOKEN)",) $(if $(LABEL),--label "$(LABEL)",)

invite-list:
	@docker-compose exec -T queue-manager node /app/invite-cli.js list $(if $(STATUS),--status $(STATUS),)

invite-info:
	@docker-compose exec -T queue-manager node /app/invite-cli.js info $(TOKEN)

invite-revoke:
	@docker-compose exec -T queue-manager node /app/invite-cli.js revoke $(TOKEN)

# SSL
ssl-setup:
	@echo "Setting up SSL with Let's Encrypt..."
	certbot --nginx -d $(DOMAIN)

ssl-renew:
	certbot renew

# Maintenance
check-token:
	@expires=$$(jq -r '.claudeAiOauth.expiresAt' secrets/.credentials.json 2>/dev/null); \
	if [ -z "$$expires" ] || [ "$$expires" = "null" ]; then \
		echo "❌ No OAuth token found in secrets/.credentials.json"; exit 1; \
	fi; \
	now=$$(date +%s)000; \
	remaining=$$(( ($$expires - $$now) / 1000 / 60 )); \
	if [ $$remaining -lt 0 ]; then \
		echo "❌ Token EXPIRED ($$(( $$remaining * -1 )) minutes ago)"; exit 1; \
	elif [ $$remaining -lt 60 ]; then \
		echo "⚠️  Token expires in $$remaining minutes - renew soon"; \
	else \
		echo "✓ Token valid for $$remaining minutes ($$(( $$remaining / 60 )) hours)"; \
	fi

refresh-token:
	@mkdir -p secrets
	@echo "Starting Claude for authentication..."
	@echo "Exit Claude after login completes (Ctrl+C or type 'exit')"
	@docker run -it --rm \
		--user root \
		--entrypoint bash \
		-v $(PWD)/secrets:/home/devuser/.claude \
		jira-demo-container:latest \
		-c "chown -R devuser:node /home/devuser/.claude && su devuser -c 'claude'"
	@echo ""
	@echo "✓ Credentials saved to secrets/"
	@chmod 644 secrets/.credentials.json secrets/.claude.json 2>/dev/null || true
	@$(MAKE) check-token

clean:
	docker-compose down -v
	docker system prune -f

restart:
	docker-compose restart

# Observability
otel-logs:
	docker-compose logs -f lgtm promtail redis-exporter

otel-reset:
	@echo "Resetting observability data..."
	docker-compose stop lgtm
	docker volume rm jira-demo_lgtm-data || true
	docker-compose up -d lgtm
	@echo "LGTM stack restarted with fresh data"

shell-queue:
	docker-compose exec queue-manager sh

shell-demo:
	docker run -it --rm \
		-e JIRA_API_TOKEN=$(JIRA_API_TOKEN) \
		-e JIRA_EMAIL=$(JIRA_EMAIL) \
		-e JIRA_SITE_URL=$(JIRA_SITE_URL) \
		-v $(PWD)/secrets/.credentials.json:/home/devuser/.claude/.credentials.json:ro \
		-v $(PWD)/secrets/.claude.json:/home/devuser/.claude/.claude.json:ro \
		jira-demo-container:latest

# Testing
test-landing:
	@open http://localhost:8080

test-terminal:
	@open http://localhost:7681

# Run scenario in debug mode (auto-advance, no prompts)
# Usage: make run-scenario SCENARIO=issue
#        make run-scenario SCENARIO=search DELAY=5
run-scenario:
	@if [ -z "$(SCENARIO)" ]; then echo "Usage: make run-scenario SCENARIO=<name> [DELAY=3]"; echo "Scenarios: issue, search, agile, jsm, admin, bulk, collaborate, dev, fields, relationships, time"; exit 1; fi
	docker run --rm --entrypoint bash \
		-e TERM=xterm \
		-e JIRA_API_TOKEN=$(JIRA_API_TOKEN) \
		-e JIRA_EMAIL=$(JIRA_EMAIL) \
		-e JIRA_SITE_URL=$(JIRA_SITE_URL) \
		-e AUTOPLAY_DEBUG=true \
		-e OTEL_ENDPOINT=http://host.docker.internal:3100 \
		-v $(PWD)/secrets/.credentials.json:/home/devuser/.claude/.credentials.json:ro \
		-v $(PWD)/secrets/.claude.json:/tmp/.claude.json.source:ro \
		--add-host=host.docker.internal:host-gateway \
		jira-demo-container:latest \
		-c "/workspace/autoplay.sh --auto-advance --delay $(or $(DELAY),3) --debug $(SCENARIO)"

# =============================================================================
# Local Development Operations (for slash commands)
# =============================================================================

status-local:
	@echo "=== Local Dev Status ==="
	@printf "Health: "; curl -sf http://localhost:8080/health > /dev/null && echo "OK" || echo "FAILED"
	@printf "Queue: "; curl -s http://localhost:8080/api/status | jq -c 2>/dev/null || echo "unavailable"
	@echo "Containers:"; docker-compose ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null || echo "not running"

health-local:
	@printf "Health: "; curl -sf http://localhost:8080/health > /dev/null && echo "OK" || echo "FAILED"
	@printf "Queue API: "; curl -sf http://localhost:8080/api/status > /dev/null && echo "OK" || echo "FAILED"
	@printf "Redis: "; docker-compose exec -T redis redis-cli ping > /dev/null 2>&1 && echo "OK" || echo "FAILED"

start-local:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

stop-local:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

restart-local:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart

queue-status-local:
	@curl -s http://localhost:8080/api/status | jq

queue-reset-local:
	@echo "Resetting local queue..."
	docker-compose restart queue-manager

logs-errors-local:
	@docker-compose logs --tail=100 2>&1 | grep -iE 'error|failed|exception' || echo "No errors found"

traces-errors-local:
	@curl -s "http://localhost:3200/api/search?q={status=error}&limit=20" | jq 2>/dev/null || echo "Tempo not available"

# Skill Testing
# Usage: make test-skill SCENARIO=search
#        make test-skill SCENARIO=search MODEL=opus JUDGE_MODEL=sonnet
#        make test-skill SCENARIO=search VERBOSE=1
test-skill:
	@if [ -z "$(SCENARIO)" ]; then echo "Usage: make test-skill SCENARIO=<name> [MODEL=sonnet] [JUDGE_MODEL=haiku] [VERBOSE=1]"; exit 1; fi
	docker run --rm \
		-e JIRA_API_TOKEN=$(JIRA_API_TOKEN) \
		-e JIRA_EMAIL=$(JIRA_EMAIL) \
		-e JIRA_SITE_URL=$(JIRA_SITE_URL) \
		-v $(PWD)/secrets/.credentials.json:/home/devuser/.claude/.credentials.json:ro \
		-v $(PWD)/secrets/.claude.json:/home/devuser/.claude/.claude.json:ro \
		jira-demo-container:latest \
		python /workspace/skill-test.py /workspace/scenarios/$(SCENARIO).prompts \
			--model $(or $(MODEL),sonnet) \
			--judge-model $(or $(JUDGE_MODEL),haiku) \
			$(if $(VERBOSE),--verbose,) \
			$(if $(JSON),--json,)

# Help
help:
	@echo "JIRA Demo Management Commands"
	@echo ""
	@echo "Development:"
	@echo "  make dev            - Start local development environment"
	@echo "  make dev-down       - Stop development environment"
	@echo ""
	@echo "Production:"
	@echo "  make build          - Build all containers"
	@echo "  make deploy         - Deploy to production"
	@echo "  make restart        - Restart all services"
	@echo ""
	@echo "Monitoring:"
	@echo "  make logs           - View all logs"
	@echo "  make logs-queue     - View queue manager logs"
	@echo "  make health         - Check system health"
	@echo ""
	@echo "JIRA Sandbox:"
	@echo "  make reset-sandbox  - Reset JIRA sandbox to initial state"
	@echo "  make seed-sandbox   - Seed JIRA sandbox with demo data"
	@echo ""
	@echo "Invite Management:"
	@echo "  make invite EXPIRES=7d       - Generate invite URL (default: 48h)"
	@echo "  make invite TOKEN=demo LABEL='Demo' - Generate vanity URL (/demo)"
	@echo "  make invite EXPIRES=24h LABEL='Workshop' - Generate with label"
	@echo "  make invite-list             - List all invites"
	@echo "  make invite-list STATUS=pending - List by status"
	@echo "  make invite-info TOKEN=xxx   - Show invite details"
	@echo "  make invite-revoke TOKEN=xxx - Revoke an invite"
	@echo ""
	@echo "Observability:"
	@echo "  make otel-logs      - View LGTM stack logs"
	@echo "  make otel-reset     - Reset observability data"
	@echo ""
	@echo "Testing:"
	@echo "  make run-scenario SCENARIO=issue      - Run scenario in debug mode (auto-advance)"
	@echo "  make run-scenario SCENARIO=search DELAY=5 - Run with custom delay"
	@echo "  make test-skill SCENARIO=search       - Run skill test with assertions"
	@echo "  make test-skill SCENARIO=search MODEL=opus JUDGE_MODEL=sonnet - Custom models"
	@echo ""
	@echo "Maintenance:"
	@echo "  make check-token    - Check Claude OAuth token expiration"
	@echo "  make refresh-token  - Authenticate and refresh OAuth token"
	@echo "  make clean          - Remove all containers and volumes"
	@echo "  make ssl-setup      - Set up SSL with Let's Encrypt"
	@echo "  make shell-queue    - Open shell in queue manager"
	@echo "  make shell-demo     - Open shell in demo container"
