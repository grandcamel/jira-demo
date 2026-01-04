.PHONY: dev build deploy logs health reset-sandbox clean

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
	@docker-compose exec -T queue-manager node /app/invite-cli.js generate --expires $(or $(EXPIRES),48h) $(if $(LABEL),--label "$(LABEL)",)

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
clean:
	docker-compose down -v
	docker system prune -f

restart:
	docker-compose restart

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
	@echo "  make invite EXPIRES=24h LABEL='Workshop' - Generate with label"
	@echo "  make invite-list             - List all invites"
	@echo "  make invite-list STATUS=pending - List by status"
	@echo "  make invite-info TOKEN=xxx   - Show invite details"
	@echo "  make invite-revoke TOKEN=xxx - Revoke an invite"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean          - Remove all containers and volumes"
	@echo "  make ssl-setup      - Set up SSL with Let's Encrypt"
	@echo "  make shell-queue    - Open shell in queue manager"
	@echo "  make shell-demo     - Open shell in demo container"
